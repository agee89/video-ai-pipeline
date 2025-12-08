import boto3
import os

def upload_to_storage(file_path: str, object_name: str) -> str:
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
    
    url = f"{os.getenv('STORAGE_ENDPOINT')}/{bucket}/{object_name}"
    
    return url