import os
from google.cloud import storage
import datetime

# ------------------------------------------------------------------
# ⚙️ CONFIGURATION
# ------------------------------------------------------------------
KEY_PATH = "gcp_key.json" 

# ⚠️ ACTION REQUIRED:
# Copy the EXACT name from your Google Cloud Console > Cloud Storage > Buckets
BUCKET_NAME = "civic-app-issues-bucket" 

# 📸 PUT YOUR IMAGE FILENAME HERE
LOCAL_IMAGE_PATH = "pothole1.jpg" 

def test_upload():
    # 1. Setup Environment
    if not os.path.exists(KEY_PATH):
        print(f"❌ Error: Could not find key file at '{KEY_PATH}'")
        return

    if not os.path.exists(LOCAL_IMAGE_PATH):
        print(f"❌ Error: Could not find local image at '{LOCAL_IMAGE_PATH}'")
        return

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = KEY_PATH
    print(f"🔑 Loaded credentials from: {KEY_PATH}")

    # 2. Generate Unique Filename
    file_extension = LOCAL_IMAGE_PATH.split(".")[-1] if "." in LOCAL_IMAGE_PATH else "jpg"
    remote_blob_name = f"test_upload_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.{file_extension}"

    try:
        # 3. Initialize Client
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)

        # 4. Upload directly (Skipping bucket.exists() to avoid extra permission errors)
        print(f"🚀 Uploading '{LOCAL_IMAGE_PATH}' to bucket '{BUCKET_NAME}'...")
        
        blob = bucket.blob(remote_blob_name)
        blob.upload_from_filename(LOCAL_IMAGE_PATH)

        # 5. Verify Public Access
        print(f"✅ Upload successful!")
        print(f"🌍 Public URL: {blob.public_url}")
        print("---")
        print("👉 Click the link above to verify.")

    except Exception as e:
        print(f"❌ FAILED: {e}")
        print("---")
        print("💡 TIP: If you see '403 Forbidden', double-check:")
        print(f"   1. Is the bucket name '{BUCKET_NAME}' correct?")
        print("   2. Does your Service Account have 'Storage Object Admin' role?")

if __name__ == "__main__":
    test_upload()