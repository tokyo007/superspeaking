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
        """
        Standardize audio file using ffmpeg as recommended by SpeechSuper:
        ffmpeg -i input.mp3 -acodec pcm_s16le -ac 1 -ar 16000 output.wav
        
        Special handling for M4A files which need different processing
        """
        if not self._check_ffmpeg_availability():
            # If ffmpeg is not available, return original file and log warning
            print("Warning: ffmpeg not available. Using original audio file.")
            return input_path
        
        # Create standardized output file path - always output as WAV
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        output_dir = os.path.dirname(input_path)
        standardized_path = os.path.join(output_dir, f"{base_name}_standardized.wav")
        
        try:
            # Run ffmpeg command with M4A-specific handling
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
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)  # Increased timeout
            
            if result.returncode == 0:
                print(f"Audio standardized successfully: {standardized_path}")
                print(f"Original size: {os.path.getsize(input_path)} bytes")
                print(f"Standardized size: {os.path.getsize(standardized_path)} bytes")
                return standardized_path
            else:
                print(f"ffmpeg failed with return code {result.returncode}")
                print(f"ffmpeg stderr: {result.stderr}")
                print(f"ffmpeg stdout: {result.stdout}")
                return input_path
                
        except subprocess.TimeoutExpired:
            print("ffmpeg timeout - file may be too large or complex")
            return input_path
        except Exception as e:
            print(f"Error during audio standardization: {str(e)}")
            return input_path

    def _generate_signature(self, timestamp, connect_str):
        """Generate signature for API authentication"""
        sig_str = self.app_key + timestamp + connect_str
        sig_sha1 = hmac.new(
            self.secret_key.encode('utf-8'),
            sig_str.encode('utf-8'),
            hashlib.sha1
        ).hexdigest()
        return base64.b64encode(sig_sha1.encode('utf-8')).decode('utf-8')

    def assess_scripted_sentence(self, audio_file_path, reference_text):
        """Scripted English sentence pronunciation assessment"""
        return self._make_assessment_request(
            audio_file_path=audio_file_path,
            core_type="sent.eval.promax",
            ref_text=reference_text
        )

    def assess_scripted_paragraph(self, audio_file_path, reference_text):
        """Scripted English paragraph pronunciation assessment"""
        return self._make_assessment_request(
            audio_file_path=audio_file_path,
            core_type="para.eval",
            ref_text=reference_text
        )

    def assess_pte_speech(self, audio_file_path, reference_text):
        """Semi-scripted English PTE speech assessment"""
        return self._make_assessment_request(
            audio_file_path=audio_file_path,
            core_type="pte.eval",
            ref_text=reference_text
        )

    def assess_ielts_speech(self, audio_file_path, question_prompt="What's your favorite food?", 
                           test_type="ielts", model="non_native"):
        """Unscripted English IELTS speech assessment API Pro"""
        timestamp = str(int(time.time()))
        connect_str = self.app_key + timestamp  # Fixed: should be app_key + timestamp
        core_type = "speak.eval.pro"
        
        # Generate signature
        signature = self._generate_signature(timestamp, connect_str)
        
        # Prepare the request URL with proper encoding
        params = {
            'sig': signature,
            'connect': connect_str,
            'coreType': core_type,
            'testType': test_type,
            'questionPrompt': quote_plus(question_prompt),
            'model': model,
            'penalizeOfftopic': '1',
            'audioType': 'wav'
        }
        
        url = f"{self.base_url}?" + "&".join([f"{k}={v}" for k, v in params.items()])
        
        return self._send_audio_request(url, audio_file_path)

    def assess_transcribe_and_score(self, audio_file_path, question_prompt="Tell me about yourself"):
        """Unscripted English transcribe and score"""
        timestamp = str(int(time.time()))
        connect_str = self.app_key + timestamp  # Fixed: should be app_key + timestamp
        core_type = "asr.eval"
        
        # Generate signature
        signature = self._generate_signature(timestamp, connect_str)
        
        # Prepare the request URL with proper encoding
        params = {
            'sig': signature,
            'connect': connect_str,
            'coreType': core_type,
            'questionPrompt': quote_plus(question_prompt),
            'audioType': 'wav'
        }
        
        url = f"{self.base_url}?" + "&".join([f"{k}={v}" for k, v in params.items()])
        
        return self._send_audio_request(url, audio_file_path)

    def _make_assessment_request(self, audio_file_path, core_type, ref_text):
        """Generic method for scripted assessments with proper URL encoding"""
        timestamp = str(int(time.time()))
        connect_str = self.app_key + timestamp
        
        # Generate signature
        signature = self._generate_signature(timestamp, connect_str)
        
        # Properly encode the reference text
        encoded_ref_text = quote_plus(ref_text)
        
        # Prepare the request URL with proper encoding
        url = f"{self.base_url}?sig={signature}&connect={connect_str}&coreType={core_type}&refText={encoded_ref_text}&audioType=wav"
        
        return self._send_audio_request(url, audio_file_path)

    def _send_audio_request(self, url, audio_file_path):
        """Send audio file to API with standardization and enhanced error handling"""
        # Standardize audio file first
        standardized_path = self._standardize_audio(audio_file_path)
        
        try:
            # Read standardized audio file
            with open(standardized_path, 'rb') as audio_file:
                audio_data = audio_file.read()
            
            print(f"=== API REQUEST DEBUG INFO ===")
            print(f"Original file: {audio_file_path}")
            print(f"Standardized file: {standardized_path}")
            print(f"Audio file size: {len(audio_data)} bytes")
            print(f"Request URL: {url}")
            
            # Validate audio data
            if len(audio_data) == 0:
                raise Exception("Audio file is empty after processing")
            
            if len(audio_data) > 16 * 1024 * 1024:  # 16MB limit
                raise Exception(f"Audio file too large: {len(audio_data)} bytes (max 16MB)")
            
            # Prepare headers
            headers = {
                'Request-Index': '0',
                'Content-Type': 'application/octet-stream'
            }
            
            print(f"Request headers: {headers}")
            
            response = requests.post(url, data=audio_data, headers=headers, timeout=60)
            
            print(f"=== API RESPONSE DEBUG INFO ===")
            print(f"Response status code: {response.status_code}")
            print(f"Response headers: {dict(response.headers)}")
            print(f"Response content length: {len(response.content)}")
            print(f"Response content type: {response.headers.get('content-type', 'unknown')}")
            
            # Check if response is successful
            if response.status_code != 200:
                error_msg = f"API returned status {response.status_code}"
                if response.text:
                    print(f"Error response body: {response.text[:1000]}...")  # First 1000 chars
                    error_msg += f": {response.text[:200]}"  # Include first 200 chars in error
                raise Exception(error_msg)
            
            # Check if response has content
            if not response.content:
                raise Exception("API returned empty response")
            
            # Check content type
            content_type = response.headers.get('content-type', '')
            if 'html' in content_type.lower():
                print(f"ERROR: Received HTML response instead of JSON")
                print(f"Response body: {response.text[:500]}...")
                raise Exception(f"API returned HTML instead of JSON. This usually indicates an authentication or parameter error.")
            
            # Try to parse JSON response
            try:
                json_response = response.json()
                print(f"Successfully parsed JSON response")
                return json_response
            except ValueError as e:
                print(f"JSON parse error: {str(e)}")
                print(f"Response text (first 500 chars): {response.text[:500]}...")
                
                # Check if it's an HTML error page
                if response.text.strip().startswith('<'):
                    raise Exception(f"API returned HTML error page instead of JSON. Check your API keys and parameters.")
                else:
                    raise Exception(f"Invalid JSON response from API. Response starts with: {response.text[:100]}")
            
        except requests.exceptions.Timeout:
            raise Exception("API request timed out (60 seconds)")
        except requests.exceptions.ConnectionError:
            raise Exception("Unable to connect to SpeechSuper API")
        except requests.exceptions.RequestException as e:
            raise Exception(f"API request failed: {str(e)}")
        finally:
            # Clean up standardized file if it's different from original
            if standardized_path != audio_file_path and os.path.exists(standardized_path):
                try:
                    os.remove(standardized_path)
                    print(f"Cleaned up temporary file: {standardized_path}")
                except Exception as e:
                    print(f"Warning: Could not clean up temporary file: {e}")

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
    ffmpeg_available = speechsuper_client._check_ffmpeg_availability()
    return jsonify({
        'status': 'healthy', 
        'timestamp': time.time(),
        'ffmpeg_available': ffmpeg_available,
        'audio_processing': 'enabled' if ffmpeg_available else 'disabled'
    })

@app.route('/api/debug-auth', methods=['GET'])
def debug_auth():
    """Debug endpoint to test API authentication without audio"""
    try:
        # Check if API keys are set
        if app.config['SPEECHSUPER_APP_KEY'] == 'your_app_key_here':
            return jsonify({'error': 'SPEECHSUPER_APP_KEY not configured'}), 400
        
        if app.config['SPEECHSUPER_SECRET_KEY'] == 'your_secret_key_here':
            return jsonify({'error': 'SPEECHSUPER_SECRET_KEY not configured'}), 400
        
        # Test basic authentication signature generation
        timestamp = str(int(time.time()))
        connect_str = app.config['SPEECHSUPER_APP_KEY'] + timestamp  # FIXED: This should be app_key + timestamp
        
        # Generate signature - the sig_str should be: app_key + timestamp + connect_str
        # But since connect_str = app_key + timestamp, sig_str becomes: app_key + timestamp + (app_key + timestamp)
        sig_str = app.config['SPEECHSUPER_APP_KEY'] + timestamp + connect_str
        sig_sha1 = hmac.new(
            app.config['SPEECHSUPER_SECRET_KEY'].encode('utf-8'),
            sig_str.encode('utf-8'),
            hashlib.sha1
        ).hexdigest()
        signature = base64.b64encode(sig_sha1.encode('utf-8')).decode('utf-8')
        
        # Create a simple test URL (without audio)
        test_url = f"https://api.speechsuper.com/?sig={signature}&connect={connect_str}&coreType=sent.eval.promax&refText=test&audioType=wav"
        
        return jsonify({
            'success': True,
            'app_key_length': len(app.config['SPEECHSUPER_APP_KEY']),
            'secret_key_length': len(app.config['SPEECHSUPER_SECRET_KEY']),
            'timestamp': timestamp,
            'connect_str': connect_str,
            'connect_str_length': len(connect_str),
            'signature': signature,
            'sig_str_for_debug': sig_str,  # Added for debugging
            'test_url': test_url,
            'message': 'Authentication parameters generated successfully'
        })
        
    except Exception as e:
        return jsonify({'error': f'Debug failed: {str(e)}'}), 500
def check_audio():
    """Endpoint to check and standardize audio format"""
    try:
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400
        
        audio_file = request.files['audio']
        if audio_file.filename == '':
            return jsonify({'error': 'No audio file selected'}), 400
        
        filename = secure_filename(audio_file.filename)
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        audio_file.save(temp_path)
        
        try:
            # Check original file info
            original_size = os.path.getsize(temp_path)
            
            # Try to standardize
            standardized_path = speechsuper_client._standardize_audio(temp_path)
            
            result = {
                'success': True,
                'original_file': filename,
                'original_size_mb': round(original_size / (1024*1024), 2),
                'ffmpeg_available': speechsuper_client._check_ffmpeg_availability()
            }
            
            if standardized_path != temp_path:
                standardized_size = os.path.getsize(standardized_path)
                result['standardized'] = True
                result['standardized_size_mb'] = round(standardized_size / (1024*1024), 2)
                result['size_change'] = round(((standardized_size - original_size) / original_size) * 100, 1)
                # Clean up standardized file
                os.remove(standardized_path)
            else:
                result['standardized'] = False
                result['message'] = 'No standardization applied (ffmpeg not available or file already optimal)'
            
            return jsonify(result)
            
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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

@app.route('/api/assess-paragraph', methods=['POST'])
def assess_paragraph():
    """Endpoint for scripted paragraph pronunciation assessment"""
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
            result = speechsuper_client.assess_scripted_paragraph(temp_path, reference_text)
            return jsonify({
                'success': True,
                'assessment_type': 'Scripted Paragraph (para.eval)',
                'assessment': result,
                'reference_text': reference_text
            })
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/assess-pte', methods=['POST'])
def assess_pte():
    """Endpoint for semi-scripted PTE speech assessment"""
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
            result = speechsuper_client.assess_pte_speech(temp_path, reference_text)
            return jsonify({
                'success': True,
                'assessment_type': 'Semi-scripted PTE (pte.eval)',
                'assessment': result,
                'reference_text': reference_text
            })
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/assess-ielts', methods=['POST'])
def assess_ielts():
    """Endpoint for unscripted IELTS speech assessment"""
    try:
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400
        
        audio_file = request.files['audio']
        if audio_file.filename == '':
            return jsonify({'error': 'No audio file selected'}), 400
        
        question_prompt = request.form.get('question_prompt', "What's your favorite food?")
        test_type = request.form.get('test_type', 'ielts')
        model = request.form.get('model', 'non_native')
        
        filename = secure_filename(audio_file.filename)
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        audio_file.save(temp_path)
        
        try:
            result = speechsuper_client.assess_ielts_speech(temp_path, question_prompt, test_type, model)
            return jsonify({
                'success': True,
                'assessment_type': 'Unscripted IELTS (speak.eval.pro)',
                'assessment': result,
                'question_prompt': question_prompt,
                'test_type': test_type
            })
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/assess-transcribe', methods=['POST'])
def assess_transcribe():
    """Endpoint for unscripted transcribe and score assessment"""
    try:
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400
        
        audio_file = request.files['audio']
        if audio_file.filename == '':
            return jsonify({'error': 'No audio file selected'}), 400
        
        question_prompt = request.form.get('question_prompt', "Tell me about yourself")
        
        filename = secure_filename(audio_file.filename)
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        audio_file.save(temp_path)
        
        try:
            result = speechsuper_client.assess_transcribe_and_score(temp_path, question_prompt)
            return jsonify({
                'success': True,
                'assessment_type': 'Transcribe and Score (asr.eval)',
                'assessment': result,
                'question_prompt': question_prompt
            })
        finally:
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
    <title>SpeechSuper Assessment MVP - All Core Types</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 1200px;
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
            margin-bottom: 30px;
        }
        .section {
            margin: 30px 0;
            padding: 25px;
            border: 2px solid #ddd;
            border-radius: 8px;
            background-color: #fafafa;
        }
        .section h2 {
            color: #2c3e50;
            margin-top: 0;
            border-bottom: 2px solid #3498db;
            padding-bottom: 10px;
        }
        .core-type {
            background: #e8f4fd;
            padding: 8px 12px;
            border-radius: 4px;
            font-family: monospace;
            font-weight: bold;
            margin-bottom: 15px;
            display: inline-block;
        }
        .form-group {
            margin: 15px 0;
        }
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
            color: #34495e;
        }
        input, textarea, select {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            box-sizing: border-box;
            font-size: 14px;
        }
        textarea {
            min-height: 80px;
            resize: vertical;
        }
        button {
            background: linear-gradient(135deg, #3498db, #2980b9);
            color: white;
            padding: 12px 24px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
            font-weight: bold;
            transition: all 0.3s ease;
        }
        button:hover {
            background: linear-gradient(135deg, #2980b9, #1f4e79);
            transform: translateY(-1px);
        }
        .result {
            margin-top: 20px;
            padding: 15px;
            border-radius: 4px;
            background-color: #f8f9fa;
            border-left: 4px solid #28a745;
        }
        .error {
            background-color: #f8d7da;
            color: #721c24;
            border-left-color: #dc3545;
        }
        .success {
            background-color: #d4edda;
            color: #155724;
            border-left-color: #28a745;
        }
        .loading {
            display: none;
            text-align: center;
            padding: 20px;
            color: #3498db;
        }
        .sample-text {
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            padding: 10px;
            border-radius: 4px;
            margin-bottom: 10px;
            font-style: italic;
        }
        .description {
            color: #666;
            font-size: 14px;
            margin-bottom: 15px;
            line-height: 1.4;
        }
        pre {
            background: #f4f4f4;
            padding: 10px;
            border-radius: 4px;
            overflow-x: auto;
            max-height: 400px;
            overflow-y: auto;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎯 SpeechSuper Assessment MVP - All Core Types</h1>
        
        <!-- Audio Format Guidance -->
        <div class="section" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;">
            <h2 style="color: white; border-bottom: 2px solid white;">📊 Audio Format Requirements</h2>
            <div style="background: rgba(255,255,255,0.1); padding: 15px; border-radius: 8px; margin: 15px 0;">
                <h3 style="margin-top: 0; color: #fff;">SpeechSuper Recommended Format:</h3>
                <div style="font-family: monospace; background: rgba(0,0,0,0.3); padding: 10px; border-radius: 4px; margin: 10px 0;">
                    <strong>ffmpeg -i input.mp3 -acodec pcm_s16le -ac 1 -ar 16000 output.wav</strong>
                </div>
                <ul style="margin: 10px 0; line-height: 1.6;">
                    <li><strong>Format:</strong> WAV with PCM encoding</li>
                    <li><strong>Sample Rate:</strong> 16kHz (16000 Hz)</li>
                    <li><strong>Channels:</strong> Mono (1 channel)</li>
                    <li><strong>Bit Depth:</strong> 16-bit</li>
                    <li><strong>Supported Formats:</strong> WAV, MP3, OPUS, OGG, AMR</li>
                </ul>
            </div>
            
            <!-- Audio Check Tool -->
            <div style="background: rgba(255,255,255,0.15); padding: 15px; border-radius: 8px;">
                <h3 style="margin-top: 0; color: #fff;">🔧 Audio Format Checker</h3>
                <p style="margin-bottom: 15px;">Upload a file to check its format and see if automatic standardization is available:</p>
                <form id="audioCheckForm" enctype="multipart/form-data" style="margin-bottom: 15px;">
                    <input type="file" id="audioCheckFile" name="audio" accept="audio/*" required 
                           style="margin-bottom: 10px; padding: 8px; border-radius: 4px; border: none;">
                    <button type="submit" style="background: #fff; color: #667eea; margin-left: 10px;">Check Audio Format</button>
                </form>
                <div class="loading" id="loadingCheck" style="color: #fff;">Checking audio format...</div>
                <div id="resultCheck" class="result" style="display: none; background: rgba(255,255,255,0.9); color: #333;"></div>
            </div>
        </div>
        
        <!-- Debug Section -->
        <div class="section" style="background: #fff3cd; border: 2px solid #ffc107;">
            <h2 style="color: #856404;">🐛 Debug & Troubleshooting</h2>
            <div class="description">
                Use these tools to diagnose API connection issues and verify your setup.
            </div>
            
            <div style="margin: 20px 0;">
                <button onclick="testAuth()" style="background: #ffc107; color: #212529; margin-right: 10px;">Test API Authentication</button>
                <button onclick="checkHealth()" style="background: #17a2b8; color: white; margin-right: 10px;">Check Health Status</button>
                <button onclick="showAudioTest()" style="background: #28a745; color: white;">Test Audio Upload</button>
            </div>
            
            <!-- Audio Upload Test Form (initially hidden) -->
            <div id="audioTestForm" style="display: none; margin: 20px 0; padding: 15px; background: rgba(255,255,255,0.5); border-radius: 8px;">
                <h4>🎵 Audio Upload Test</h4>
                <p>Test your audio file processing without calling the SpeechSuper API:</p>
                <form id="audioUploadTest" enctype="multipart/form-data">
                    <input type="file" id="testAudioFile" name="audio" accept="audio/*" required style="margin-bottom: 10px;">
                    <input type="text" id="testRefText" name="reference_text" placeholder="Reference text..." value="Hello world" style="margin-bottom: 10px;">
                    <button type="submit" style="background: #28a745; color: white;">Test Upload & Processing</button>
                </form>
            </div>
            
            <div class="loading" id="loadingDebug" style="color: #856404;">Testing connection...</div>
            <div id="resultDebug" class="result" style="display: none;"></div>
        </div>
        <div class="section">
            <h2>1. Scripted Sentence Pronunciation Assessment</h2>
            <div class="core-type">coreType: "sent.eval.promax"</div>
            <div class="description">
                Comprehensive pronunciation assessment at phoneme, syllable, word, and sentence levels with advanced features like stress analysis and mispronunciation detection.
            </div>
            <form id="sentenceForm" enctype="multipart/form-data">
                <div class="form-group">
                    <label for="audioFile1">Audio File (WAV, MP3, etc.):</label>
                    <input type="file" id="audioFile1" name="audio" accept="audio/*" required>
                </div>
                <div class="form-group">
                    <label for="referenceText1">Reference Text:</label>
                    <div class="sample-text">Sample: "The successful warrior is the average man with laser-like focus."</div>
                    <textarea id="referenceText1" name="reference_text" rows="3" 
                              placeholder="Enter the sentence that should be spoken..." required>The successful warrior is the average man with laser-like focus.</textarea>
                </div>
                <button type="submit">Assess Sentence Pronunciation</button>
            </form>
            <div class="loading" id="loading1">Analyzing sentence pronunciation...</div>
            <div id="result1" class="result" style="display: none;"></div>
        </div>

        <!-- Scripted Paragraph Assessment -->
        <div class="section">
            <h2>2. Scripted Paragraph Pronunciation Assessment</h2>
            <div class="core-type">coreType: "para.eval"</div>
            <div class="description">
                Pronunciation assessment for longer passages, providing comprehensive analysis of rhythm, fluency, and pronunciation across multiple sentences.
            </div>
            <form id="paragraphForm" enctype="multipart/form-data">
                <div class="form-group">
                    <label for="audioFile2">Audio File (WAV, MP3, etc.):</label>
                    <input type="file" id="audioFile2" name="audio" accept="audio/*" required>
                </div>
                <div class="form-group">
                    <label for="referenceText2">Reference Paragraph:</label>
                    <div class="sample-text">Sample paragraph about communication and technology</div>
                    <textarea id="referenceText2" name="reference_text" rows="5" 
                              placeholder="Enter the paragraph that should be spoken..." required>In today's digital age, effective communication has become more important than ever before. Technology has revolutionized the way we connect with others, allowing us to share ideas and collaborate across vast distances. However, with these advancements come new challenges. We must learn to navigate the complexities of digital communication while maintaining the human touch that makes our interactions meaningful and authentic.</textarea>
                </div>
                <button type="submit">Assess Paragraph Pronunciation</button>
            </form>
            <div class="loading" id="loading2">Analyzing paragraph pronunciation...</div>
            <div id="result2" class="result" style="display: none;"></div>
        </div>

        <!-- Semi-scripted PTE Assessment -->
        <div class="section">
            <h2>3. Semi-scripted PTE Speech Assessment</h2>
            <div class="core-type">coreType: "pte.eval"</div>
            <div class="description">
                PTE Academic-style assessment for tasks like "Read Aloud" where content is provided but delivery is evaluated for fluency and pronunciation.
            </div>
            <form id="pteForm" enctype="multipart/form-data">
                <div class="form-group">
                    <label for="audioFile3">Audio File (WAV, MP3, etc.):</label>
                    <input type="file" id="audioFile3" name="audio" accept="audio/*" required>
                </div>
                <div class="form-group">
                    <label for="referenceText3">PTE Reference Text:</label>
                    <div class="sample-text">Sample PTE Academic passage about environmental science</div>
                    <textarea id="referenceText3" name="reference_text" rows="4" 
                              placeholder="Enter the PTE passage that should be read aloud..." required>Climate change represents one of the most significant challenges facing humanity in the twenty-first century. Rising global temperatures, melting ice caps, and extreme weather patterns are clear indicators of our planet's changing climate. Scientists worldwide agree that immediate action is required to reduce greenhouse gas emissions and transition to sustainable energy sources.</textarea>
                </div>
                <button type="submit">Assess PTE Speech</button>
            </form>
            <div class="loading" id="loading3">Analyzing PTE speech assessment...</div>
            <div id="result3" class="result" style="display: none;"></div>
        </div>

        <!-- Unscripted IELTS Assessment -->
        <div class="section">
            <h2>4. Unscripted IELTS Speech Assessment Pro</h2>
            <div class="core-type">coreType: "speak.eval.pro"</div>
            <div class="description">
                Comprehensive assessment of spontaneous speech including pronunciation, fluency, grammar, vocabulary, and content relevance with IELTS scoring.
            </div>
            <form id="ieltsForm" enctype="multipart/form-data">
                <div class="form-group">
                    <label for="audioFile4">Audio File (WAV, MP3, etc.):</label>
                    <input type="file" id="audioFile4" name="audio" accept="audio/*" required>
                </div>
                <div class="form-group">
                    <label for="questionPrompt1">IELTS Question Prompt:</label>
                    <div class="sample-text">Sample IELTS Speaking questions</div>
                    <select id="questionPromptSelect" onchange="updateQuestionPrompt()">
                        <option value="custom">Custom Question</option>
                        <option value="food">What's your favorite food and why?</option>
                        <option value="travel">Describe a place you would like to visit and explain why.</option>
                        <option value="technology">How has technology changed the way people communicate?</option>
                        <option value="education">What do you think is the most important subject to study and why?</option>
                        <option value="environment">What can individuals do to help protect the environment?</option>
                    </select>
                    <textarea id="questionPrompt1" name="question_prompt" rows="3" 
                              placeholder="Enter the IELTS question prompt...">What's your favorite food and why?</textarea>
                </div>
                <div class="form-group">
                    <label for="testType1">Test Type:</label>
                    <select id="testType1" name="test_type">
                        <option value="ielts">IELTS</option>
                        <option value="pte">PTE</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="model1">Speaker Model:</label>
                    <select id="model1" name="model">
                        <option value="non_native">Non-Native Speaker</option>
                        <option value="native">Native Speaker</option>
                    </select>
                </div>
                <button type="submit">Assess IELTS Speech</button>
            </form>
            <div class="loading" id="loading4">Analyzing IELTS speech assessment...</div>
            <div id="result4" class="result" style="display: none;"></div>
        </div>

        <!-- Transcribe and Score Assessment -->
        <div class="section">
            <h2>5. Unscripted Transcribe and Score Assessment</h2>
            <div class="core-type">coreType: "asr.eval"</div>
            <div class="description">
                Automatic speech recognition with pronunciation scoring. Transcribes speech and provides pronunciation feedback without requiring reference text.
            </div>
            <form id="transcribeForm" enctype="multipart/form-data">
                <div class="form-group">
                    <label for="audioFile5">Audio File (WAV, MP3, etc.):</label>
                    <input type="file" id="audioFile5" name="audio" accept="audio/*" required>
                </div>
                <div class="form-group">
                    <label for="questionPrompt2">Question Context (Optional):</label>
                    <div class="sample-text">Sample open-ended questions for natural speech</div>
                    <select id="transcribePromptSelect" onchange="updateTranscribePrompt()">
                        <option value="custom">Custom Question</option>
                        <option value="yourself">Tell me about yourself</option>
                        <option value="day">Describe your typical day</option>
                        <option value="hobbies">What are your hobbies and interests?</option>
                        <option value="goals">What are your goals for the future?</option>
                        <option value="experience">Describe a memorable experience you've had</option>
                    </select>
                    <textarea id="questionPrompt2" name="question_prompt" rows="2" 
                              placeholder="Enter the question context (optional)...">Tell me about yourself</textarea>
                </div>
                <button type="submit">Transcribe and Score Speech</button>
            </form>
            <div class="loading" id="loading5">Transcribing and scoring speech...</div>
            <div id="result5" class="result" style="display: none;"></div>
        </div>
    </div>

    <script>
        // Sample question prompts
        const questionPrompts = {
            food: "What's your favorite food and why?",
            travel: "Describe a place you would like to visit and explain why.",
            technology: "How has technology changed the way people communicate?",
            education: "What do you think is the most important subject to study and why?",
            environment: "What can individuals do to help protect the environment?"
        };

        const transcribePrompts = {
            yourself: "Tell me about yourself",
            day: "Describe your typical day",
            hobbies: "What are your hobbies and interests?",
            goals: "What are your goals for the future?",
            experience: "Describe a memorable experience you've had"
        };

        function updateQuestionPrompt() {
            const select = document.getElementById('questionPromptSelect');
            const textarea = document.getElementById('questionPrompt1');
            if (select.value !== 'custom') {
                textarea.value = questionPrompts[select.value];
            }
        }

        function updateTranscribePrompt() {
            const select = document.getElementById('transcribePromptSelect');
            const textarea = document.getElementById('questionPrompt2');
            if (select.value !== 'custom') {
                textarea.value = transcribePrompts[select.value];
            }
        }

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

        // Debug functions
        function showAudioTest() {
            const testForm = document.getElementById('audioTestForm');
            testForm.style.display = testForm.style.display === 'none' ? 'block' : 'none';
        }

        async function testAuth() {
            showLoading('loadingDebug');
            document.getElementById('resultDebug').style.display = 'none';
            
            try {
                const response = await fetch('/api/debug-auth');
                const data = await response.json();
                
                if (data.success) {
                    let message = `
                        <h4>🔑 Authentication Test Results:</h4>
                        <p><strong>App Key Length:</strong> ${data.app_key_length} characters</p>
                        <p><strong>Secret Key Length:</strong> ${data.secret_key_length} characters</p>
                        <p><strong>Timestamp:</strong> ${data.timestamp}</p>
                        <p><strong>Signature Generated:</strong> ✅ Success</p>
                        <p><strong>Status:</strong> ${data.message}</p>
                        <details style="margin-top: 10px;">
                            <summary>Technical Details (Click to expand)</summary>
                            <p><strong>Test URL:</strong><br><code style="word-break: break-all; font-size: 12px;">${data.test_url}</code></p>
                        </details>
                    `;
                    showResult('resultDebug', message);
                } else {
                    showResult('resultDebug', 'Authentication Error: ' + data.error, true);
                }
            } catch (error) {
                showResult('resultDebug', 'Connection Error: ' + error.message, true);
            } finally {
                hideLoading('loadingDebug');
            }
        }

        async function checkHealth() {
            showLoading('loadingDebug');
            document.getElementById('resultDebug').style.display = 'none';
            
            try {
                const response = await fetch('/health');
                const data = await response.json();
                
                let message = `
                    <h4>🏥 Health Check Results:</h4>
                    <p><strong>Status:</strong> ${data.status}</p>
                    <p><strong>FFmpeg Available:</strong> ${data.ffmpeg_available ? '✅ Yes' : '❌ No'}</p>
                    <p><strong>Audio Processing:</strong> ${data.audio_processing}</p>
                    <p><strong>Timestamp:</strong> ${new Date(data.timestamp * 1000).toLocaleString()}</p>
                `;
                
                if (!data.ffmpeg_available) {
                    message += `<p style="color: orange;"><strong>⚠️ Note:</strong> Audio files will be used in original format without optimization.</p>`;
                }
                
                showResult('resultDebug', message);
            } catch (error) {
                showResult('resultDebug', 'Health Check Error: ' + error.message, true);
            } finally {
                hideLoading('loadingDebug');
            }
        }

        // Audio upload test form handler
        document.getElementById('audioUploadTest').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            showLoading('loadingDebug');
            document.getElementById('resultDebug').style.display = 'none';
            
            const formData = new FormData(this);
            
            try {
                const response = await fetch('/api/test-audio-upload', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await response.json();
                
                if (data.success) {
                    let message = `
                        <h4>🎵 Audio Upload Test Results:</h4>
                        <p><strong>File:</strong> ${data.original_filename} (${data.file_extension})</p>
                        <p><strong>Original Size:</strong> ${data.original_size_mb} MB (${data.original_size_bytes} bytes)</p>
                        <p><strong>Reference Text:</strong> "${data.reference_text}" (${data.reference_text_length} chars)</p>
                        <p><strong>FFmpeg Available:</strong> ${data.ffmpeg_available ? '✅ Yes' : '❌ No'}</p>
                    `;
                    
                    if (data.standardization_applied) {
                        message += `
                            <p><strong>Audio Processing:</strong> ✅ Applied</p>
                            <p><strong>Processed Size:</strong> ${data.standardized_size_mb} MB (${data.size_change_percent > 0 ? '+' : ''}${data.size_change_percent}%)</p>
                            <p><strong>Readable:</strong> ${data.standardized_readable ? '✅ Yes' : '❌ No'}</p>
                        `;
                        if (!data.standardized_readable) {
                            message += `<p style="color: red;"><strong>Error:</strong> ${data.standardization_error}</p>`;
                        }
                    } else {
                        message += `<p><strong>Audio Processing:</strong> ❌ Not applied</p>`;
                    }
                    
                    message += `
                        <p><strong>API URL Length:</strong> ${data.url_length} characters</p>
                        <details style="margin-top: 10px;">
                            <summary>Generated API URL (Click to expand)</summary>
                            <code style="word-break: break-all; font-size: 11px;">${data.test_api_url}</code>
                        </details>
                    `;
                    
                    showResult('resultDebug', message);
                } else {
                    showResult('resultDebug', 'Upload Test Error: ' + data.error, true);
                }
            } catch (error) {
                showResult('resultDebug', 'Test Error: ' + error.message, true);
            } finally {
                hideLoading('loadingDebug');
            }
        });

        // Audio check form handler
        document.getElementById('audioCheckForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            showLoading('loadingCheck');
            document.getElementById('resultCheck').style.display = 'none';
            
            const formData = new FormData(this);
            
            try {
                const response = await fetch('/api/check-audio', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await response.json();
                
                if (data.success) {
                    let message = `
                        <h4>Audio Check Results:</h4>
                        <p><strong>File:</strong> ${data.original_file}</p>
                        <p><strong>Size:</strong> ${data.original_size_mb} MB</p>
                        <p><strong>FFmpeg Available:</strong> ${data.ffmpeg_available ? '✅ Yes' : '❌ No'}</p>
                    `;
                    
                    if (data.standardized) {
                        message += `
                            <p><strong>Standardization:</strong> ✅ Applied</p>
                            <p><strong>New Size:</strong> ${data.standardized_size_mb} MB (${data.size_change > 0 ? '+' : ''}${data.size_change}%)</p>
                            <p style="color: green;">Your audio will be automatically optimized for better API results!</p>
                        `;
                    } else {
                        message += `
                            <p><strong>Standardization:</strong> ${data.message}</p>
                            ${!data.ffmpeg_available ? '<p style="color: orange;">⚠️ FFmpeg not available - audio will be used as-is</p>' : ''}
                        `;
                    }
                    
                    showResult('resultCheck', message);
                } else {
                    showResult('resultCheck', 'Error: ' + data.error, true);
                }
            } catch (error) {
                showResult('resultCheck', 'Error: ' + error.message, true);
            } finally {
                hideLoading('loadingCheck');
            }
        });
        document.getElementById('sentenceForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            await handleFormSubmission(this, '/api/assess-sentence', 'loading1', 'result1');
        });

        document.getElementById('paragraphForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            await handleFormSubmission(this, '/api/assess-paragraph', 'loading2', 'result2');
        });

        document.getElementById('pteForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            await handleFormSubmission(this, '/api/assess-pte', 'loading3', 'result3');
        });

        document.getElementById('ieltsForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            await handleFormSubmission(this, '/api/assess-ielts', 'loading4', 'result4');
        });

        document.getElementById('transcribeForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            await handleFormSubmission(this, '/api/assess-transcribe', 'loading5', 'result5');
        });

        async function handleFormSubmission(form, endpoint, loadingId, resultId) {
            showLoading(loadingId);
            document.getElementById(resultId).style.display = 'none';
            
            const formData = new FormData(form);
            
            try {
                const response = await fetch(endpoint, {
                    method: 'POST',
                    body: formData
                });
                
                const data = await response.json();
                
                if (data.success) {
                    showResult(resultId, formatResult(data));
                } else {
                    showResult(resultId, 'Error: ' + data.error, true);
                }
            } catch (error) {
                showResult(resultId, 'Error: ' + error.message, true);
            } finally {
                hideLoading(loadingId);
            }
        }
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)