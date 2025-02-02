from typing import AsyncIterator, List, Dict, Any, Callable
from loguru import logger

from .agent_interface import AgentInterface
from ..output_types import SentenceOutput
from ..stateless_llm.stateless_llm_interface import StatelessLLMInterface
from ...chat_history_manager import get_history
from ..transformers import (
    sentence_divider,
    actions_extractor,
    tts_filter,
    display_processor,
)
from ...config_manager import TTSPreprocessorConfig
from ..input_types import BatchInput, TextSource, ImageSource


class BasicMemoryAgent(AgentInterface):
    """
    Agent with basic chat memory using a list to store messages.
    Implements text-based responses with sentence processing pipeline.
    """

    _system: str = """You are an error message repeater. 
        Your job is repeating this error message: 
        'No system prompt set. Please set a system prompt'. 
        Don't say anything else.
        """

    def __init__(
        self,
        llm: StatelessLLMInterface,
        system: str,
        live2d_model,
        tts_preprocessor_config: TTSPreprocessorConfig = None,
        faster_first_response: bool = True,
        segment_method: str = "pysbd",
    ):
        """
        Initialize the agent with LLM, system prompt and configuration

        Args:
            llm: StatelessLLMInterface - The LLM to use
            system: str - System prompt
            live2d_model: Live2dModel - Model for expression extraction
            tts_preprocessor_config: TTSPreprocessorConfig - Configuration for TTS preprocessing
            faster_first_response: bool - Whether to enable faster first response
            segment_method: str - Method for sentence segmentation
        """
        super().__init__()
        self._memory = []
        self._live2d_model = live2d_model
        self._tts_preprocessor_config = tts_preprocessor_config
        self._faster_first_response = faster_first_response
        self._segment_method = segment_method
        # Flag to ensure a single interrupt handling per conversation
        self._interrupt_handled = False
        self._set_llm(llm)
        self.set_system(system)
        logger.info("BasicMemoryAgent initialized.")

    def _set_llm(self, llm: StatelessLLMInterface):
        """
        Set the (stateless) LLM to be used for chat completion.
        Instead of assigning directly to `self.chat`, store it to `_chat_function`
        so that the async method chat remains intact.

        Args:
            llm: StatelessLLMInterface - the LLM instance.
        """
        self._llm = llm
        self._chat_function = self._chat_function_factory(llm.chat_completion)

    def set_system(self, system: str):
        """
        Set the system prompt
        system: str
            the system prompt
        """
        logger.debug(f"Memory Agent: Setting system prompt: '''{system}'''")
        self._system = system

    def _add_message(self, message: str | List[Dict[str, Any]], role: str):
        """Add a message to the memory"""
        if isinstance(message, list):
            text_content = ""
            for item in message:
                if item.get("type") == "text":
                    text_content += item["text"]
        else:
            text_content = message

        self._memory.append({
            "role": role,
            "content": text_content,
        })

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        """Load the memory from chat history"""
        messages = get_history(conf_uid, history_uid)

        self._memory = []
        self._memory.append(
            {
                "role": "system",
                "content": self._system,
            }
        )

        for msg in messages:
            self._memory.append(
                {
                    "role": "user" if msg["role"] == "human" else "assistant",
                    "content": msg["content"],
                }
            )

    def handle_interrupt(self, heard_response: str) -> None:
        """
        Handle an interruption by the user.

        Args:
            heard_response: str - The part of the AI response heard by the user before interruption
        """
        if self._interrupt_handled:
            return

        self._interrupt_handled = True

        if self._memory and self._memory[-1]["role"] == "assistant":
            self._memory[-1]["content"] = heard_response + "..."
        else:
            if heard_response:
                self._memory.append({
                    "role": "assistant",
                    "content": heard_response + "...",
                })
        self._memory.append({
            "role": "system",
            "content": "[Interrupted by user]",
        })

    def _to_text_prompt(self, input_data: BatchInput) -> str:
        """
        Format BatchInput into a prompt string for the LLM.

        Args:
            input_data: BatchInput - The input data containing texts and images

        Returns:
            str - Formatted message string
        """
        message_parts = []

        # Process text inputs in order
        for text_data in input_data.texts:
            if text_data.source == TextSource.INPUT:
                message_parts.append(text_data.content)
            elif text_data.source == TextSource.CLIPBOARD:
                message_parts.append(f"[Clipboard content: {text_data.content}]")

        # Process images in order
        if input_data.images:
            message_parts.append("\nImages in this message:")
            for i, img_data in enumerate(input_data.images, 1):
                source_desc = {
                    ImageSource.CAMERA: "captured from camera",
                    ImageSource.SCREEN: "screenshot",
                    ImageSource.CLIPBOARD: "from clipboard",
                    ImageSource.UPLOAD: "uploaded",
                }[img_data.source]
                message_parts.append(f"- Image {i} ({source_desc})")

        return "\n".join(message_parts)

    def _to_messages(self, input_data: BatchInput) -> List[Dict[str, Any]]:
        """
        Prepare messages list with image support.
        """
        messages = self._memory.copy()
        
        if input_data.images:
            content = []
            text_content = self._to_text_prompt(input_data)
            content.append({"type": "text", "text": text_content})
            
            for img_data in input_data.images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": img_data.data, "detail": "auto"},
                })
            
            user_message = {
                "role": "user",
                "content": content
            }
        else:
            user_message = {
                "role": "user", 
                "content": self._to_text_prompt(input_data)
            }

        messages.append(user_message)
        self._add_message(user_message["content"], "user")
        return messages

    def _chat_function_factory(
        self, chat_func: Callable[[List[Dict[str, Any]], str], AsyncIterator[str]]
    ) -> Callable[..., AsyncIterator[SentenceOutput]]:
        """
        Create the chat pipeline with transformers

        The pipeline:
        LLM tokens -> sentence_divider -> actions_extractor -> display_processor -> tts_filter
        """

        @tts_filter(self._tts_preprocessor_config)
        @display_processor()
        @actions_extractor(self._live2d_model)
        @sentence_divider(
            faster_first_response=self._faster_first_response,
            segment_method=self._segment_method,
            valid_tags=["think"],
        )
        async def chat_with_memory(input_data: BatchInput) -> AsyncIterator[str]:
            """
            Chat implementation with memory and processing pipeline

            Args:
                input_data: BatchInput

            Returns:
                AsyncIterator[str] - Token stream from LLM
            """

            messages = self._to_messages(input_data)

            # Get token stream from LLM
            token_stream = chat_func(messages, self._system)
            complete_response = ""

            async for token in token_stream:
                yield token
                complete_response += token

            # Store complete response
            self._add_message(complete_response, "assistant")

        return chat_with_memory

    async def chat(self, input_data: BatchInput) -> AsyncIterator[SentenceOutput]:
        """Chat method that will be used to generate responses."""
        self.reset_interrupt()
        try:
            async for output in self._chat_function(input_data):
                yield output
        except Exception as e:
            logger.error(f"Error in chat: {e}")
            raise

    def reset_interrupt(self) -> None:
        """
        Reset the interrupt handled flag for a new conversation.
        """
        self._interrupt_handled = False

    def start_group_conversation(self, human_name: str, ai_participants: List[str]) -> None:
        """
        Start a group conversation by adding a system message that informs the AI about 
        the conversation participants.

        Args:
            human_name: str - Name of the human participant
            ai_participants: List[str] - Names of other AI participants in the conversation
        """
        other_ais = ", ".join(name for name in ai_participants)
        
        group_context = (
            f"You are in a group conversation. "
            f"The human participant is {human_name}. "
            f"The other AI participants are: {other_ais}. "
            f"Avoid using `:` to indicate your response. Just speak naturally."
            f"You are free to address other AI participants as you would in a real conversation."
            f"Try to keep your responses short and concise. Engage in the interaction actively."
        )
        
        self._memory.append({
            "role": "user",
            "content": group_context
        })
        
        logger.debug(f"Added group conversation context: '''{group_context}'''")
