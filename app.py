import os
import json
import base64
import hashlib
import hmac
import time
import requests
import subprocess
from urllib.parse import quote_plus
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

    def _check_ffmpeg_availability(self):
        """Check if ffmpeg is available on the system"""
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _standardize_audio(self, input_path):
        """Standardize audio file using ffmpeg as recommended by SpeechSuper"""
        if not self._check_ffmpeg_availability():
            print("Warning: ffmpeg not available. Using original audio file.")
            return input_path
        
        # Create standardized output file path - always output as WAV
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        output_dir = os.path.dirname(input_path)
        standardized_path = os.path.join(output_dir, f"{base_name}_standardized.wav")
        
        try:
            # Run ffmpeg command with recommended settings
            cmd = [
                'ffmpeg',
                '-i', input_path,
                '-acodec', 'pcm_s16le',  # 16-bit PCM
                '-ac', '1',              # Mono (1 channel)
                '-ar', '16000',          # 16kHz sample rate
                '-f', 'wav',             # Force WAV output format
                '-y',                    # Overwrite output file
                standardized_path
            ]
            
            print(f"Running ffmpeg command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                print(f"Audio standardized successfully: {standardized_path}")
                return standardized_path
            else:
                print(f"ffmpeg failed: {result.stderr}")
                return input_path
                
        except subprocess.TimeoutExpired:
            print("ffmpeg timeout - using original file")
            return input_path
        except Exception as e:
            print(f"Error during audio standardization: {str(e)}")
            return input_path

    def _generate_speechsuper_signatures(self, timestamp, user_id="guest"):
        """Generate both connect and start signatures as per SpeechSuper format"""
        # Connect signature: appKey + timestamp + secretKey
        connect_str = (self.app_key + timestamp + self.secret_key).encode("utf-8")
        connect_sig = hashlib.sha1(connect_str).hexdigest()
        
        # Start signature: appKey + timestamp + userId + secretKey  
        start_str = (self.app_key + timestamp + user_id + self.secret_key).encode("utf-8")
        start_sig = hashlib.sha1(start_str).hexdigest()
        
        return connect_sig, start_sig

    def _make_speechsuper_request(self, audio_file_path, core_type, ref_text, user_id="guest"):
        """Make request using correct SpeechSuper format"""
        # Standardize audio first
        standardized_path = self._standardize_audio(audio_file_path)
        
        try:
            timestamp = str(int(time.time()))
            connect_sig, start_sig = self._generate_speechsuper_signatures(timestamp, user_id)
            
            # Build the JSON parameters exactly like the sample
            params = {
                "connect": {
                    "cmd": "connect",
                    "param": {
                        "sdk": {
                            "version": 16777472,
                            "source": 9,
                            "protocol": 2
                        },
                        "app": {
                            "applicationId": self.app_key,
                            "sig": connect_sig,
                            "timestamp": timestamp
                        }
                    }
                },
                "start": {
                    "cmd": "start",
                    "param": {
                        "app": {
                            "userId": user_id,
                            "applicationId": self.app_key,
                            "timestamp": timestamp,
                            "sig": start_sig
                        },
                        "audio": {
                            "audioType": "wav",
                            "channel": 1,
                            "sampleBytes": 2,
                            "sampleRate": 16000
                        },
                        "request": {
                            "coreType": core_type,
                            "refText": ref_text,
                            "tokenId": "tokenId"
                        }
                    }
                }
            }
            
            # Convert to JSON string
            json_params = json.dumps(params)
            
            # Build URL with coreType
            url = f"{self.base_url}{core_type}"
            
            print(f"=== SPEECHSUPER CORRECT FORMAT ===")
            print(f"URL: {url}")
            print(f"Timestamp: {timestamp}")
            print(f"Connect sig: {connect_sig}")
            print(f"Start sig: {start_sig}")
            print(f"JSON params length: {len(json_params)}")
            
            # Prepare the request exactly like the sample
            data = {'text': json_params}
            headers = {"Request-Index": "0"}
            
            with open(standardized_path, 'rb') as audio_file:
                files = {"audio": audio_file}
                
                print(f"Making POST request with files and data")
                response = requests.post(url, data=data, headers=headers, files=files, timeout=60)
                
                print(f"Response status: {response.status_code}")
                print(f"Response content: {response.text[:500]}")
                
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError:
                        # If not JSON, return the text
                        return {"raw_response": response.text}
                else:
                    raise Exception(f"API returned status {response.status_code}: {response.text[:300]}")
                    
        except requests.exceptions.RequestException as e:
            raise Exception(f"Request failed: {str(e)}")
        finally:
            # Clean up standardized file if different from original
            if standardized_path != audio_file_path and os.path.exists(standardized_path):
                try:
                    os.remove(standardized_path)
                except:
                    pass

    def assess_scripted_sentence(self, audio_file_path, reference_text):
        """Scripted English sentence pronunciation assessment using correct format"""
        return self._make_speechsuper_request(audio_file_path, "sent.eval.promax", reference_text)

    def assess_scripted_paragraph(self, audio_file_path, reference_text):
        """Scripted English paragraph pronunciation assessment using correct format"""
        return self._make_speechsuper_request(audio_file_path, "para.eval", reference_text)

    def assess_pte_speech(self, audio_file_path, reference_text):
        """Semi-scripted English PTE speech assessment using correct format"""
        return self._make_speechsuper_request(audio_file_path, "pte.eval", reference_text)

# Initialize API client
speechsuper_client = SpeechSuperAPI(
    app.config['SPEECHSUPER_APP_KEY'],
    app.config['SPEECHSUPER_SECRET_KEY']
)

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/microphone-test')
def microphone_test():
    return render_template_string(MICROPHONE_TEST_HTML)

@app.route('/health')
def health_check():
    ffmpeg_available = speechsuper_client._check_ffmpeg_availability()
    return jsonify({
        'status': 'healthy', 
        'timestamp': time.time(),
        'ffmpeg_available': ffmpeg_available,
        'audio_processing': 'enabled' if ffmpeg_available else 'disabled'
    })

@app.route('/api/debug-auth', methods=['GET'])
def debug_auth():
    """Debug endpoint to test API authentication"""
    try:
        if app.config['SPEECHSUPER_APP_KEY'] == 'your_app_key_here':
            return jsonify({'error': 'SPEECHSUPER_APP_KEY not configured'}), 400
        
        if app.config['SPEECHSUPER_SECRET_KEY'] == 'your_secret_key_here':
            return jsonify({'error': 'SPEECHSUPER_SECRET_KEY not configured'}), 400
        
        app_key = app.config['SPEECHSUPER_APP_KEY']
        secret_key = app.config['SPEECHSUPER_SECRET_KEY']
        timestamp = str(int(time.time()))
        
        # Test new signature format
        connect_sig, start_sig = speechsuper_client._generate_speechsuper_signatures(timestamp)
        
        return jsonify({
            'success': True,
            'app_key_preview': app_key[:4] + '...' + app_key[-4:] if len(app_key) > 8 else app_key,
            'app_key_length': len(app_key),
            'secret_key_length': len(secret_key),
            'timestamp': timestamp,
            'connect_signature': connect_sig,
            'start_signature': start_sig,
            'new_format': True,
            'message': 'Using correct SpeechSuper format'
        })
        
    except Exception as e:
        return jsonify({'error': f'Debug failed: {str(e)}'}), 500

@app.route('/api/assess-sentence', methods=['POST'])
def assess_sentence():
    """Endpoint for scripted sentence pronunciation assessment"""
    try:
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400
        
        audio_file = request.files['audio']
        if audio_file.filename == '':
            return jsonify({'error': 'No audio file selected'}), 400
        
        reference_text = request.form.get('reference_text')
        if not reference_text:
            return jsonify({'error': 'Reference text is required'}), 400
        
        filename = secure_filename(audio_file.filename)
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        audio_file.save(temp_path)
        
        try:
            result = speechsuper_client.assess_scripted_sentence(temp_path, reference_text)
            
            return jsonify({
                'success': True,
                'assessment_type': 'Scripted Sentence (sent.eval.promax)',
                'assessment': result,
                'reference_text': reference_text
            })
            
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# HTML Template for main page
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>SpeechSuper MVP</title>
</head>
<body>
    <h1>SpeechSuper Assessment MVP</h1>
    <p><a href="/microphone-test">Go to Microphone Test</a></p>
    <p><a href="/api/debug-auth">Test Authentication</a></p>
</body>
</html>
'''

# HTML Template for microphone test
MICROPHONE_TEST_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SpeechSuper Microphone Test</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 15px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
        }
        h1 {
            text-align: center;
            color: #667eea;
            margin-bottom: 30px;
            font-size: 2.5em;
        }
        .test-section {
            background: #f8f9fa;
            padding: 30px;
            border-radius: 10px;
            margin: 20px 0;
            border-left: 5px solid #667eea;
        }
        .reference-text {
            background: #e3f2fd;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
            font-size: 1.2em;
            text-align: center;
            font-weight: bold;
            color: #1976d2;
        }
        .controls {
            text-align: center;
            margin: 30px 0;
        }
        button {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 25px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            margin: 10px;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        }
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.3);
        }
        button:disabled {
            background: #ccc;
            cursor: not-allowed;
            transform: none;
        }
        .record-btn {
            background: linear-gradient(135deg, #ff6b6b, #ee5a24);
        }
        .stop-btn {
            background: linear-gradient(135deg, #feca57, #ff9ff3);
        }
        .test-btn {
            background: linear-gradient(135deg, #48dbfb, #0abde3);
        }
        .status {
            text-align: center;
            padding: 15px;
            margin: 20px 0;
            border-radius: 8px;
            font-weight: bold;
        }
        .status.recording {
            background: #ffebee;
            color: #c62828;
            border: 2px solid #ff5722;
        }
        .status.ready {
            background: #e8f5e8;
            color: #2e7d32;
            border: 2px solid #4caf50;
        }
        .status.testing {
            background: #fff3e0;
            color: #ef6c00;
            border: 2px solid #ff9800;
        }
        .result {
            margin-top: 20px;
            padding: 20px;
            border-radius: 8px;
            background: #f0f8ff;
            border-left: 4px solid #2196f3;
        }
        .error {
            background: #ffebee;
            border-left-color: #f44336;
            color: #c62828;
        }
        .success {
            background: #e8f5e8;
            border-left-color: #4caf50;
            color: #2e7d32;
        }
        .debug-info {
            background: #f5f5f5;
            padding: 15px;
            border-radius: 5px;
            margin: 10px 0;
            font-family: monospace;
            font-size: 12px;
            max-height: 200px;
            overflow-y: auto;
        }
        .audio-controls {
            margin: 20px 0;
            text-align: center;
        }
        audio {
            width: 100%;
            max-width: 400px;
        }
        .instructions {
            background: #fffde7;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
            border: 1px solid #fbc02d;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎤 SpeechSuper Live Test</h1>
        
        <div class="instructions">
            <h3>📋 How to Test:</h3>
            <ol>
                <li><strong>Click "Start Recording"</strong> to begin capturing audio</li>
                <li><strong>Read the sentence aloud</strong> clearly and naturally</li>
                <li><strong>Click "Stop Recording"</strong> when finished</li>
                <li><strong>Click "Test with SpeechSuper"</strong> to get your pronunciation score</li>
            </ol>
        </div>

        <div class="test-section">
            <h2>🎯 Scripted Sentence Pronunciation Test</h2>
            <p><strong>API Endpoint:</strong> <code>sent.eval.promax</code></p>
            
            <div class="reference-text">
                "The successful warrior is the average man with laser-like focus."
            </div>
            
            <div class="controls">
                <button id="recordBtn" class="record-btn">🎤 Start Recording</button>
                <button id="stopBtn" class="stop-btn" disabled>⏹️ Stop Recording</button>
                <button id="testBtn" class="test-btn" disabled>🚀 Test with SpeechSuper</button>
            </div>
            
            <div id="status" class="status">Click "Start Recording" to begin</div>
            
            <div class="audio-controls" id="audioControls" style="display: none;">
                <h4>🔊 Your Recording:</h4>
                <audio id="audioPlayback" controls></audio>
            </div>
            
            <div id="result" class="result" style="display: none;"></div>
        </div>
    </div>

    <script>
        let mediaRecorder;
        let audioChunks = [];
        let recordedBlob;

        const recordBtn = document.getElementById('recordBtn');
        const stopBtn = document.getElementById('stopBtn');
        const testBtn = document.getElementById('testBtn');
        const status = document.getElementById('status');
        const result = document.getElementById('result');
        const audioControls = document.getElementById('audioControls');
        const audioPlayback = document.getElementById('audioPlayback');

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            status.innerHTML = '❌ Your browser does not support microphone recording';
            status.className = 'status error';
            recordBtn.disabled = true;
        }

        recordBtn.addEventListener('click', startRecording);
        stopBtn.addEventListener('click', stopRecording);
        testBtn.addEventListener('click', testWithSpeechSuper);

        async function startRecording() {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ 
                    audio: {
                        sampleRate: 16000,
                        channelCount: 1,
                        echoCancellation: true,
                        noiseSuppression: true
                    }
                });

                mediaRecorder = new MediaRecorder(stream, {
                    mimeType: 'audio/webm;codecs=opus'
                });

                audioChunks = [];

                mediaRecorder.ondataavailable = event => {
                    if (event.data.size > 0) {
                        audioChunks.push(event.data);
                    }
                };

                mediaRecorder.onstop = () => {
                    recordedBlob = new Blob(audioChunks, { type: 'audio/webm' });
                    
                    const audioUrl = URL.createObjectURL(recordedBlob);
                    audioPlayback.src = audioUrl;
                    audioControls.style.display = 'block';
                    
                    status.innerHTML = '✅ Recording complete! You can play it back and then test with SpeechSuper.';
                    status.className = 'status ready';
                    testBtn.disabled = false;
                    
                    stream.getTracks().forEach(track => track.stop());
                };

                mediaRecorder.start();

                recordBtn.disabled = true;
                stopBtn.disabled = false;
                testBtn.disabled = true;
                status.innerHTML = '🔴 Recording... Speak the sentence clearly!';
                status.className = 'status recording';
                
                result.style.display = 'none';

            } catch (error) {
                console.error('Error accessing microphone:', error);
                status.innerHTML = '❌ Error accessing microphone. Please allow microphone access and try again.';
                status.className = 'status error';
            }
        }

        function stopRecording() {
            if (mediaRecorder && mediaRecorder.state === 'recording') {
                mediaRecorder.stop();
            }
            
            recordBtn.disabled = false;
            stopBtn.disabled = true;
        }

        async function testWithSpeechSuper() {
            if (!recordedBlob) {
                showResult('No recording available. Please record audio first.', true);
                return;
            }

            status.innerHTML = '🧪 Testing with SpeechSuper API...';
            status.className = 'status testing';
            testBtn.disabled = true;

            try {
                const formData = new FormData();
                const audioFile = new File([recordedBlob], 'recording.webm', { type: 'audio/webm' });
                formData.append('audio', audioFile);
                formData.append('reference_text', 'The successful warrior is the average man with laser-like focus.');

                const response = await fetch('/api/assess-sentence', {
                    method: 'POST',
                    body: formData
                });

                console.log('API Response Status:', response.status);

                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(`HTTP ${response.status}: ${errorText.substring(0, 200)}`);
                }

                const data = await response.json();
                console.log('API Response Data:', data);

                if (data.success) {
                    let resultHtml = `
                        <h3>🎉 Assessment Results</h3>
                        <div class="debug-info">
                            <strong>Assessment Type:</strong> ${data.assessment_type}<br>
                            <strong>Reference Text:</strong> "${data.reference_text}"
                        </div>
                    `;

                    if (data.assessment && data.assessment.result) {
                        const result = data.assessment.result;
                        resultHtml += `
                            <h4>📊 Scores:</h4>
                            <ul>
                                ${result.overall ? `<li><strong>Overall:</strong> ${result.overall}</li>` : ''}
                                ${result.pronunciation ? `<li><strong>Pronunciation:</strong> ${result.pronunciation}</li>` : ''}
                                ${result.fluency ? `<li><strong>Fluency:</strong> ${result.fluency}</li>` : ''}
                                ${result.completeness ? `<li><strong>Completeness:</strong> ${result.completeness}</li>` : ''}
                                ${result.rhythm ? `<li><strong>Rhythm:</strong> ${result.rhythm}</li>` : ''}
                            </ul>
                        `;
                    }

                    resultHtml += `
                        <details style="margin-top: 15px;">
                            <summary>🔍 Full API Response (Click to expand)</summary>
                            <div class="debug-info">${JSON.stringify(data, null, 2)}</div>
                        </details>
                    `;

                    showResult(resultHtml, false);
                    status.innerHTML = '✅ Test completed successfully!';
                    status.className = 'status ready';
                } else {
                    throw new Error(data.error || 'Unknown API error');
                }

            } catch (error) {
                console.error('Test error:', error);
                let errorMessage = `
                    <h3>❌ Test Failed</h3>
                    <p><strong>Error:</strong> ${error.message}</p>
                    <div class="debug-info">
                        <strong>Troubleshooting Tips:</strong><br>
                        • Check that your API keys are set correctly in Render<br>
                        • Verify your internet connection<br>
                        • Try recording a shorter, clearer audio clip<br>
                        • Check browser console for additional errors
                    </div>
                `;
                
                showResult(errorMessage, true);
                status.innerHTML = '❌ Test failed. Check the error details below.';
                status.className = 'status error';
            } finally {
                testBtn.disabled = false;
            }
        }

        function showResult(content, isError = false) {
            result.innerHTML = content;
            result.className = 'result ' + (isError ? 'error' : 'success');
            result.style.display = 'block';
        }

        status.innerHTML = 'Ready to record. Click "Start Recording" to begin.';
        status.className = 'status ready';
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)