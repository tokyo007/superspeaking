import os
import json
import base64
import hashlib
import hmac
import time
import requests
from flask import Flask, request, jsonify, render_template_string
from werkzeug.utils import secure_filename
import tempfile

app = Flask(__name__)

# Configuration
class Config:
    # Replace with your actual keys from SpeechSuper
    SPEECHSUPER_APP_KEY = os.environ.get('SPEECHSUPER_APP_KEY', 'your_app_key_here')
    SPEECHSUPER_SECRET_KEY = os.environ.get('SPEECHSUPER_SECRET_KEY', 'your_secret_key_here')
    SPEECHSUPER_API_URL = "https://api.speechsuper.com/"
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    UPLOAD_FOLDER = tempfile.gettempdir()

app.config.from_object(Config)

class SpeechSuperAPI:
    def __init__(self, app_key, secret_key):
        self.app_key = app_key
        self.secret_key = secret_key
        self.base_url = "https://api.speechsuper.com/"

    def _generate_signature(self, timestamp, connect_str):
        """Generate signature for API authentication"""
        sig_str = self.app_key + timestamp + connect_str
        sig_sha1 = hmac.new(
            self.secret_key.encode('utf-8'),
            sig_str.encode('utf-8'),
            hashlib.sha1
        ).hexdigest()
        return base64.b64encode(sig_sha1.encode('utf-8')).decode('utf-8')

    def assess_pronunciation(self, audio_file_path, reference_text, core_type="sent.eval.promax"):
        """
        Assess pronunciation using SpeechSuper API
        
        Args:
            audio_file_path: Path to the audio file
            reference_text: The reference text that should be spoken
            core_type: Type of assessment (sent.eval.promax for sentence evaluation)
        """
        timestamp = str(int(time.time()))
        connect_str = self.app_key + timestamp
        
        # Generate signature
        signature = self._generate_signature(timestamp, connect_str)
        
        # Prepare the request
        url = f"{self.base_url}?sig={signature}&connect={connect_str}&coreType={core_type}&refText={reference_text}&audioType=wav"
        
        # Read audio file
        with open(audio_file_path, 'rb') as audio_file:
            audio_data = audio_file.read()
        
        # Prepare headers
        headers = {
            'Request-Index': '0',
            'Content-Type': 'application/octet-stream'
        }
        
        try:
            response = requests.post(url, data=audio_data, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"API request failed: {str(e)}")

    def assess_spontaneous_speech(self, audio_file_path, question_prompt="What's your favorite food?", 
                                 test_type="ielts", model="non_native"):
        """
        Assess spontaneous speech using SpeechSuper API
        
        Args:
            audio_file_path: Path to the audio file
            question_prompt: The question that was asked
            test_type: Type of test (ielts, pte, etc.)
            model: Transcription model (non_native or native)
        """
        timestamp = str(int(time.time()))
        connect_str = self.app_key + timestamp
        core_type = "speak.eval.pro"
        
        # Generate signature
        signature = self._generate_signature(timestamp, connect_str)
        
        # Prepare the request URL with parameters
        params = {
            'sig': signature,
            'connect': connect_str,
            'coreType': core_type,
            'testType': test_type,
            'questionPrompt': question_prompt,
            'model': model,
            'penalizeOfftopic': '1',
            'audioType': 'wav'
        }
        
        url = f"{self.base_url}?" + "&".join([f"{k}={v}" for k, v in params.items()])
        
        # Read audio file
        with open(audio_file_path, 'rb') as audio_file:
            audio_data = audio_file.read()
        
        # Prepare headers
        headers = {
            'Request-Index': '0',
            'Content-Type': 'application/octet-stream'
        }
        
        try:
            response = requests.post(url, data=audio_data, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"API request failed: {str(e)}")

# Initialize API client
speechsuper_client = SpeechSuperAPI(
    app.config['SPEECHSUPER_APP_KEY'],
    app.config['SPEECHSUPER_SECRET_KEY']
)

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': time.time()})

@app.route('/api/assess-pronunciation', methods=['POST'])
def assess_pronunciation():
    """Endpoint for scripted pronunciation assessment"""
    try:
        # Check if audio file is present
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400
        
        audio_file = request.files['audio']
        if audio_file.filename == '':
            return jsonify({'error': 'No audio file selected'}), 400
        
        # Get reference text
        reference_text = request.form.get('reference_text')
        if not reference_text:
            return jsonify({'error': 'Reference text is required'}), 400
        
        # Get optional parameters
        core_type = request.form.get('core_type', 'sent.eval.promax')
        
        # Save uploaded file temporarily
        filename = secure_filename(audio_file.filename)
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        audio_file.save(temp_path)
        
        try:
            # Call SpeechSuper API
            result = speechsuper_client.assess_pronunciation(
                temp_path, reference_text, core_type
            )
            
            return jsonify({
                'success': True,
                'assessment': result,
                'reference_text': reference_text
            })
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_path):
                os.remove(temp_path)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/assess-spontaneous', methods=['POST'])
def assess_spontaneous():
    """Endpoint for spontaneous speech assessment"""
    try:
        # Check if audio file is present
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400
        
        audio_file = request.files['audio']
        if audio_file.filename == '':
            return jsonify({'error': 'No audio file selected'}), 400
        
        # Get optional parameters
        question_prompt = request.form.get('question_prompt', "What's your favorite food?")
        test_type = request.form.get('test_type', 'ielts')
        model = request.form.get('model', 'non_native')
        
        # Save uploaded file temporarily
        filename = secure_filename(audio_file.filename)
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        audio_file.save(temp_path)
        
        try:
            # Call SpeechSuper API
            result = speechsuper_client.assess_spontaneous_speech(
                temp_path, question_prompt, test_type, model
            )
            
            return jsonify({
                'success': True,
                'assessment': result,
                'question_prompt': question_prompt,
                'test_type': test_type
            })
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_path):
                os.remove(temp_path)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# HTML Template for the web interface
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pronunciation Assessment MVP</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            text-align: center;
        }
        .section {
            margin: 30px 0;
            padding: 20px;
            border: 1px solid #ddd;
            border-radius: 5px;
        }
        .form-group {
            margin: 15px 0;
        }
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
        }
        input, textarea, select {
            width: 100%;
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            box-sizing: border-box;
        }
        button {
            background-color: #007bff;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
        }
        button:hover {
            background-color: #0056b3;
        }
        .result {
            margin-top: 20px;
            padding: 15px;
            border-radius: 4px;
            background-color: #f8f9fa;
        }
        .error {
            background-color: #f8d7da;
            color: #721c24;
        }
        .success {
            background-color: #d4edda;
            color: #155724;
        }
        .loading {
            display: none;
            text-align: center;
            padding: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Pronunciation Assessment MVP</h1>
        
        <div class="section">
            <h2>Scripted Pronunciation Assessment</h2>
            <form id="pronunciationForm" enctype="multipart/form-data">
                <div class="form-group">
                    <label for="audioFile1">Audio File (WAV, MP3, etc.):</label>
                    <input type="file" id="audioFile1" name="audio" accept="audio/*" required>
                </div>
                <div class="form-group">
                    <label for="referenceText">Reference Text:</label>
                    <textarea id="referenceText" name="reference_text" rows="3" 
                              placeholder="Enter the text that should be spoken..." required>The successful warrior is the average man with laser-like focus.</textarea>
                </div>
                <div class="form-group">
                    <label for="coreType1">Assessment Type:</label>
                    <select id="coreType1" name="core_type">
                        <option value="sent.eval.promax">Sentence Evaluation (Pro Max)</option>
                        <option value="sent.eval">Sentence Evaluation (Basic)</option>
                    </select>
                </div>
                <button type="submit">Assess Pronunciation</button>
            </form>
            <div class="loading" id="loading1">Analyzing pronunciation...</div>
            <div id="result1" class="result" style="display: none;"></div>
        </div>
        
        <div class="section">
            <h2>Spontaneous Speech Assessment</h2>
            <form id="spontaneousForm" enctype="multipart/form-data">
                <div class="form-group">
                    <label for="audioFile2">Audio File (WAV, MP3, etc.):</label>
                    <input type="file" id="audioFile2" name="audio" accept="audio/*" required>
                </div>
                <div class="form-group">
                    <label for="questionPrompt">Question Prompt:</label>
                    <textarea id="questionPrompt" name="question_prompt" rows="2" 
                              placeholder="Enter the question that was asked...">What's your favorite food?</textarea>
                </div>
                <div class="form-group">
                    <label for="testType">Test Type:</label>
                    <select id="testType" name="test_type">
                        <option value="ielts">IELTS</option>
                        <option value="pte">PTE</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="model">Speaker Model:</label>
                    <select id="model" name="model">
                        <option value="non_native">Non-Native Speaker</option>
                        <option value="native">Native Speaker</option>
                    </select>
                </div>
                <button type="submit">Assess Speech</button>
            </form>
            <div class="loading" id="loading2">Analyzing speech...</div>
            <div id="result2" class="result" style="display: none;"></div>
        </div>
    </div>

    <script>
        function formatResult(data) {
            return '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
        }
        
        function showLoading(loadingId) {
            document.getElementById(loadingId).style.display = 'block';
        }
        
        function hideLoading(loadingId) {
            document.getElementById(loadingId).style.display = 'none';
        }
        
        function showResult(resultId, content, isError = false) {
            const resultDiv = document.getElementById(resultId);
            resultDiv.className = 'result ' + (isError ? 'error' : 'success');
            resultDiv.innerHTML = content;
            resultDiv.style.display = 'block';
        }

        document.getElementById('pronunciationForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            showLoading('loading1');
            document.getElementById('result1').style.display = 'none';
            
            const formData = new FormData(this);
            
            try {
                const response = await fetch('/api/assess-pronunciation', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await response.json();
                
                if (data.success) {
                    showResult('result1', formatResult(data));
                } else {
                    showResult('result1', 'Error: ' + data.error, true);
                }
            } catch (error) {
                showResult('result1', 'Error: ' + error.message, true);
            } finally {
                hideLoading('loading1');
            }
        });

        document.getElementById('spontaneousForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            showLoading('loading2');
            document.getElementById('result2').style.display = 'none';
            
            const formData = new FormData(this);
            
            try {
                const response = await fetch('/api/assess-spontaneous', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await response.json();
                
                if (data.success) {
                    showResult('result2', formatResult(data));
                } else {
                    showResult('result2', 'Error: ' + data.error, true);
                }
            } catch (error) {
                showResult('result2', 'Error: ' + error.message, true);
            } finally {
                hideLoading('loading2');
            }
        });
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)