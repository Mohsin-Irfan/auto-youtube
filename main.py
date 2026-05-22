import os
import pickle
import tempfile
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from groq import Groq
import json
import logging

# ---------- Setup ----------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# YouTube OAuth 2.0 scopes
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# ---------- Google Drive Service Account ----------
# Service account JSON string stored in GitHub secret
SERVICE_ACCOUNT_INFO = json.loads(os.environ["GOOGLE_DRIVE_SERVICE_ACCOUNT"])
from google.oauth2 import service_account
drive_creds = service_account.Credentials.from_service_account_info(
    SERVICE_ACCOUNT_INFO,
    scopes=["https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/drive.file"]
)
drive_service = build("drive", "v3", credentials=drive_creds)

# ---------- YouTube OAuth (refresh token from secret) ----------
def get_youtube_credentials():
    creds = None
    # Load refresh token from environment
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    client_config = json.loads(os.environ["YOUTUBE_CLIENT_SECRET"])
    
    if refresh_token:
        creds = Credentials(
            None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_config["installed"]["client_id"],
            client_secret=client_config["installed"]["client_secret"]
        )
        # Refresh if expired
        if creds.expired:
            creds.refresh(Request())
    else:
        # First time setup (should not happen in Action; run get_youtube_token.py locally)
        raise Exception("No refresh token found. Run get_youtube_token.py first and set YOUTUBE_REFRESH_TOKEN secret.")
    return creds

# ---------- Groq AI ----------
try:
    groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
except KeyError:
    raise Exception("GROQ_API_KEY environment variable not set. Please add it to GitHub secrets.")
except TypeError as e:
    raise Exception(f"Groq library version conflict: {e}. Please ensure groq==0.9.0 and httpx==0.27.0 are installed.")

def generate_metadata(surah_name):
    prompt = f"""You are an SEO expert for Islamic YouTube shorts. Generate YouTube metadata for a Quran Surah recitation video titled "{surah_name}".
    Return ONLY valid JSON with these keys: title, description, tags.
    - title: under 100 chars, engaging, include Surah name and "Beautiful Recitation"
    - description: 2-3 lines, include a hook, mention the Surah's meaning, and add hashtags.
    - tags: comma-separated string of 10-15 tags (e.g., Quran,Surah{surah_name},Recitation,Islamic)
    
    Example format: {{"title": "Surah Al-Fatiha - Heart-Touching Recitation", "description": "Listen to this calming recitation... #Quran #SurahAlFatiha", "tags": "Quran,Recitation,Islamic,Surah Al-Fatiha"}}"""
    
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        response_format={"type": "json_object"}
    )
    data = json.loads(response.choices[0].message.content)
    return data["title"], data["description"], data["tags"]

# ---------- Google Drive: find first video in YouTubeQueue ----------
def find_video_in_queue():
    results = drive_service.files().list(
        q="name contains 'YouTubeQueue' and mimeType contains 'video/'",
        spaces="drive",
        fields="files(id, name, mimeType, parents)",
        pageSize=1
    ).execute()
    files = results.get("files", [])
    if not files:
        logger.info("No video found in YouTubeQueue folder.")
        return None, None
    file = files[0]
    file_id = file["id"]
    file_name = file["name"]
    logger.info(f"Found video: {file_name} (ID: {file_id})")
    return file_id, file_name

def download_video(file_id, output_path):
    request = drive_service.files().get_media(fileId=file_id)
    with open(output_path, "wb") as f:
        f.write(request.execute())
    logger.info(f"Downloaded to {output_path}")

def delete_video_from_drive(file_id):
    drive_service.files().delete(fileId=file_id).execute()
    logger.info(f"Deleted video ID {file_id} from Drive")

# ---------- YouTube Upload ----------
def upload_to_youtube(video_path, title, description, tags):
    youtube = build("youtube", "v3", credentials=get_youtube_credentials())
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags.split(","),
            "categoryId": "22"  # 22 = People & Blogs
        },
        "status": {
            "privacyStatus": "public",  # or "unlisted" if you want to review first
            "selfDeclaredMadeForKids": False
        }
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )
    response = request.execute()
    logger.info(f"Uploaded successfully! Video ID: {response['id']}")
    return response["id"]

# ---------- Main ----------
def main():
    logger.info("Starting automatic upload process...")
    
    # 1. Find video in Drive
    video_id, video_name = find_video_in_queue()
    if not video_id:
        logger.info("No video to upload. Exiting.")
        return
    
    # 2. Extract surah name from filename (assume filename like "Surah Al-Fatiha.mp4")
    surah_name = os.path.splitext(video_name)[0].replace("_", " ").title()
    
    # 3. Generate metadata using Groq
    title, description, tags = generate_metadata(surah_name)
    logger.info(f"Generated Title: {title}")
    
    # 4. Download video to temp file
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = tmp.name
    download_video(video_id, tmp_path)
    
    # 5. Upload to YouTube
    try:
        upload_to_youtube(tmp_path, title, description, tags)
        # 6. Delete from Drive only if upload successful
        delete_video_from_drive(video_id)
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        # Do not delete video from Drive so it can be retried next day
    finally:
        # Cleanup temp file
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    
if __name__ == "__main__":
    main()
