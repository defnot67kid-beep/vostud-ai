const API_URL = 'http://localhost:8000';
let conversationHistory = [];

// DOM Elements
const chatHistory = document.getElementById('chatHistory');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const uploadBtn = document.getElementById('uploadBtn');
const fileInput = document.getElementById('fileInput');
const uploadStatus = document.getElementById('uploadStatus');
const quizBtn = document.getElementById('quizBtn');

// Send message
async function sendMessage() {
    const message = userInput.value.trim();
    if (!message) return;

    // Add user message to chat
    addMessage('user', message);
    userInput.value = '';

    // Add loading indicator
    const loadingMsg = addMessage('bot', '🤔 Thinking...');

    try {
        const response = await fetch(`${API_URL}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                history: conversationHistory,
                use_rag: true
            })
        });

        const data = await response.json();
        
        // Remove loading message
        loadingMsg.remove();
        
        // Add bot response
        addMessage('bot', data.response);
        
        // Update conversation history
        conversationHistory.push(
            { role: 'user', content: message },
            { role: 'assistant', content: data.response }
        );
    } catch (error) {
        loadingMsg.remove();
        addMessage('bot', '❌ Sorry, there was an error. Please try again.');
        console.error('Error:', error);
    }
}

// Upload document
async function uploadDocument() {
    const file = fileInput.files[0];
    if (!file) {
        uploadStatus.textContent = 'Please select a file first.';
        uploadStatus.className = 'error';
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    uploadStatus.textContent = 'Uploading...';
    uploadStatus.className = '';

    try {
        const response = await fetch(`${API_URL}/upload`, {
            method: 'POST',
            body: formData
        });

        const data = await response.json();
        
        if (response.ok) {
            uploadStatus.textContent = `✅ ${data.message}`;
            uploadStatus.className = 'success';
            addMessage('bot', `📚 I've processed "${file.name}". I now have ${data.chunks_processed} new pieces of information to help you study!`);
        } else {
            uploadStatus.textContent = `❌ ${data.detail || 'Upload failed'}`;
            uploadStatus.className = 'error';
        }
    } catch (error) {
        uploadStatus.textContent = '❌ Error uploading file.';
        uploadStatus.className = 'error';
        console.error('Error:', error);
    }
}

// Generate quiz
async function generateQuiz() {
    const topic = userInput.value.trim() || 'general study topics';
    
    addMessage('user', `Generate a quiz about: ${topic}`);
    userInput.value = '';

    const loadingMsg = addMessage('bot', '📝 Generating quiz...');

    try {
        const response = await fetch(`${API_URL}/quiz`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                topic: topic,
                num_questions: 5
            })
        });

        const data = await response.json();
        loadingMsg.remove();
        addMessage('bot', `📝 Here's your quiz:\n\n${data.quiz}`);
    } catch (error) {
        loadingMsg.remove();
        addMessage('bot', '❌ Sorry, could not generate quiz.');
        console.error('Error:', error);
    }
}

// Helper: Add message to chat
function addMessage(type, content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}`;
    messageDiv.textContent = content;
    chatHistory.appendChild(messageDiv);
    chatHistory.scrollTop = chatHistory.scrollHeight;
    return messageDiv;
}

// Event listeners
sendBtn.addEventListener('click', sendMessage);
userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

uploadBtn.addEventListener('click', uploadDocument);
quizBtn.addEventListener('click', generateQuiz);

// Optional: Load initial stats
async function loadStats() {
    try {
        const response = await fetch(`${API_URL}/knowledge-stats`);
        const data = await response.json();
        if (data.total_documents > 0) {
            addMessage('bot', `📊 Knowledge base has ${data.total_documents} documents loaded.`);
        }
    } catch (error) {
        console.log('Stats not available');
    }
}

loadStats();