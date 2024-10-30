from flask import Flask, render_template
from flask_socketio import SocketIO
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from google.auth.transport.requests import Request
import pickle
import os
import time
import csv
from datetime import datetime
import openai

app = Flask(__name__)
socketio = SocketIO(app)
scopes = ["https://www.googleapis.com/auth/youtube.readonly"]

# 환경 변수에서 OpenAI API 키 가져오기
openai.api_key = ""


# 호출 횟수를 기록할 변수들
openai_call_count = 0
youtube_api_call_count = 0

# CSV 파일 설정
CSV_FILENAME = 'youtube_chat_sentiment_kr.csv'
CSV_HEADERS = ['timestamp', 'author', 'message', 'sentiment', 'confidence', 'sentiment_details', 'profile_image_url']

# 중복 메시지 추적을 위한 집합
processed_message_ids = set()

def initialize_sentiment_analyzer():
    # OpenAI API를 사용하므로 별도의 모델 초기화가 필요하지 않음
    pass

def analyze_korean_sentiment(text):
    global openai_call_count  # OpenAI 호출 횟수를 추적
    try:
        # gpt-3.5-turbo 모델을 사용하도록 수정
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "user", "content": f"문장 '{text}'의 감정을 분석해 주세요. 결과는 긍정, 부정, 중립 중 하나로 알려 주세요."}
            ],
            max_tokens=50
        )

        openai_call_count += 1  # 호출 횟수 증가
        print(f"OpenAI API 호출 횟수: {openai_call_count}")

        # LLM 응답에서 감정 정보 추출
        sentiment_text = response.choices[0].message['content'].strip().lower()
        if "긍정" in sentiment_text:
            sentiment = '긍정'
            confidence = 0.8
        elif "부정" in sentiment_text:
            sentiment = '부정'
            confidence = 0.8
        else:
            sentiment = '중립'
            confidence = 0.6
        
        # 상세 점수 예시 생성 (필요에 따라 조정 가능)
        sentiment_details = {
            'negative': 0.1 if sentiment == '부정' else 0.3,
            'neutral': 0.3 if sentiment == '중립' else 0.2,
            'positive': 0.1 if sentiment == '긍정' else 0.2
        }
        
        return {
            'sentiment': sentiment,
            'confidence': confidence,
            'sentiment_details': sentiment_details
        }
    except Exception as e:
        print(f"감성 분석 중 오류 발생: {e}")
        return {
            'sentiment': '중립',
            'confidence': 0.333,
            'sentiment_details': {
                'negative': 0.333,
                'neutral': 0.334,
                'positive': 0.333
            }
        }

@app.route('/')
def index():
    return render_template('index3.html')

def save_to_csv(chat_data):
    with open(CSV_FILENAME, 'a', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=CSV_HEADERS)
        writer.writerow(chat_data)

def initialize_csv():
    if not os.path.exists(CSV_FILENAME):
        with open(CSV_FILENAME, 'w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=CSV_HEADERS)
            writer.writeheader()

def initialize_youtube_client():
    client_secrets_file = "C:\\Users\\r2com\\Downloads\\YOUR_CLIENT_SECRET_FILE.json"
    creds = None
    
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
            client_secrets_file, scopes)
        creds = flow.run_local_server(port=0)
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)
    
    return googleapiclient.discovery.build("youtube", "v3", credentials=creds)

def fetch_continuous_live_chat_messages(youtube, live_chat_id):
    global youtube_api_call_count  # YouTube API 호출 횟수를 추적
    next_page_token = None
    
    while True:
        try:
            request = youtube.liveChatMessages().list(
                liveChatId=live_chat_id,
                part="snippet,authorDetails",
                pageToken=next_page_token
            )
            response = request.execute()
            
            youtube_api_call_count += 1  # 호출 횟수 증가
            print(f"YouTube API 호출 횟수: {youtube_api_call_count}")

            for item in response.get("items", []):
                message_id = item["id"]
                if message_id in processed_message_ids:
                    continue  # 이미 처리된 메시지는 무시

                processed_message_ids.add(message_id)  # 새로운 메시지 ID를 추가
                author = item["authorDetails"]["displayName"]
                message = item["snippet"]["displayMessage"]
                profile_image_url = item["authorDetails"]["profileImageUrl"]
                
                # OpenAI API 감정 분석 수행
                sentiment_result = analyze_korean_sentiment(message)
                
                # 현재 타임스탬프 생성
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # 데이터 준비
                chat_data = {
                    'timestamp': timestamp,
                    'author': author,
                    'message': message,
                    'sentiment': sentiment_result['sentiment'],
                    'confidence': sentiment_result['confidence'],
                    'sentiment_details': str(sentiment_result['sentiment_details']),
                    'profile_image_url': profile_image_url
                }
                
                # CSV 파일에 저장
                save_to_csv(chat_data)
                
                # 소켓을 통해 클라이언트에 전송
                socketio.emit('chat_message', chat_data)
            
            # 다음 페이지 토큰 업데이트
            next_page_token = response.get("nextPageToken")
            time.sleep(5)
            
        except googleapiclient.errors.HttpError as e:
            print(f"API 요청 오류: {e}")
            break
        except Exception as e:
            print(f"예기치 못한 오류 발생: {e}")
            break

@socketio.on('connect')
def handle_connect():
    initialize_csv()
    youtube = initialize_youtube_client()
    live_chat_id = "Cg0KC3o1Q3RQdkhoNHNNKicKGFVDSEJvY2NyWmE2QkdLdUxhLVI0ZUNYQRILejVDdFB2SGg0c00"  # 실제 라이브 스트림 ID로 변경
    socketio.start_background_task(
        fetch_continuous_live_chat_messages, 
        youtube, 
        live_chat_id
    )

if __name__ == '__main__':
    socketio.run(app, debug=True)