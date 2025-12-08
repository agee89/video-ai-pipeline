import boto3
import os

def upload_to_storage(file_path: str, object_name: str) -> dict:
    """Upload file to storage and return URLs for different access contexts.
    
    Returns:
        dict with:
        - 'url': for n8n/external Docker services (minio-video:9002)
        - 'url_external': for browser/external access (localhost:9002)
    """
    s3_client = boto3.client(
        's3',
        endpoint_url=os.getenv('STORAGE_ENDPOINT'),
        aws_access_key_id=os.getenv('STORAGE_ACCESS_KEY'),
        aws_secret_access_key=os.getenv('STORAGE_SECRET_KEY')
    )
    
    bucket = os.getenv('STORAGE_BUCKET', 'video-clips')
    
    try:
        s3_client.head_bucket(Bucket=bucket)
    except:
        s3_client.create_bucket(Bucket=bucket)
    
    s3_client.upload_file(file_path, bucket, object_name)
    
    # URL for n8n and other Docker services on nca-network
    n8n_endpoint = os.getenv('STORAGE_N8N_URL', os.getenv('STORAGE_ENDPOINT'))
    n8n_url = f"{n8n_endpoint}/{bucket}/{object_name}"
    
    # External URL for browser/external access
    external_endpoint = os.getenv('STORAGE_PUBLIC_URL', os.getenv('STORAGE_ENDPOINT'))
    external_url = f"{external_endpoint}/{bucket}/{object_name}"
    
    return {
        "url": n8n_url,           # For n8n/Docker (minio-video:9002)
        "url_external": external_url  # For browser (localhost:9002)
    }