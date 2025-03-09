// 扩展AI主动说话功能，允许用户设置自定义提示词
document.addEventListener('DOMContentLoaded', function() {
    // 等待主应用加载完成
    setTimeout(function() {
        initProactiveSpeakExtension();
    }, 1000);
});

function initProactiveSpeakExtension() {
    console.log('正在初始化AI主动说话扩展...');
    
    // 创建设置面板
    const settingsPanel = document.createElement('div');
    settingsPanel.className = 'section proactive-speak-settings';
    settingsPanel.innerHTML = `
        <h2>AI主动说话设置</h2>
        <div class="setting-item">
            <label for="proactivePrompt">主动说话提示词：</label>
            <textarea id="proactivePrompt" placeholder="输入提示词，引导AI主动说话的内容，例如：'我想和你聊聊天气'"></textarea>
        </div>
        <button id="saveProactiveSettings" class="button">保存设置</button>
        <div id="proactiveStatus" class="status"></div>
    `;

    // 添加样式
    const style = document.createElement('style');
    style.textContent = `
        .proactive-speak-settings {
            margin-top: 20px;
            border: 2px solid #007bff !important;
        }
        .setting-item {
            margin-bottom: 15px;
        }
        .setting-item label {
            display: block;
            margin-bottom: 8px;
            font-weight: bold;
        }
        #proactiveStatus {
            margin-top: 10px;
        }
    `;
    document.head.appendChild(style);

    // 将设置面板添加到页面
    const body = document.body;
    const lastSection = document.querySelector('.section:last-child');
    if (lastSection) {
        body.insertBefore(settingsPanel, lastSection.nextSibling);
    } else {
        body.appendChild(settingsPanel);
    }

    // 从localStorage加载保存的设置
    const savedPrompt = localStorage.getItem('proactivePrompt') || '';
    document.getElementById('proactivePrompt').value = savedPrompt;

    // 保存设置
    document.getElementById('saveProactiveSettings').addEventListener('click', function() {
        const prompt = document.getElementById('proactivePrompt').value;
        localStorage.setItem('proactivePrompt', prompt);
        
        const statusElem = document.getElementById('proactiveStatus');
        statusElem.textContent = '设置已保存！提示词将在AI下次主动说话时生效。';
        statusElem.className = 'status success';
        
        setTimeout(() => {
            statusElem.textContent = '';
            statusElem.className = 'status';
        }, 3000);
    });

    // 拦截WebSocket消息发送
    const originalWebSocketSend = WebSocket.prototype.send;
    WebSocket.prototype.send = function(data) {
        try {
            const parsedData = JSON.parse(data);
            
            // 如果是主动说话信号，添加自定义提示词
            if (parsedData.type === 'ai-speak-signal') {
                const customPrompt = localStorage.getItem('proactivePrompt') || '';
                parsedData.proactive_prompt = customPrompt;
                console.log('已添加自定义提示词到AI主动说话信号:', customPrompt);
                return originalWebSocketSend.call(this, JSON.stringify(parsedData));
            }
        } catch (e) {
            // 如果不是JSON或解析出错，直接发送原始数据
            console.log('WebSocket数据不是JSON格式，直接发送原始数据');
        }
        
        return originalWebSocketSend.call(this, data);
    };

    console.log('AI主动说话扩展已成功加载');
} 