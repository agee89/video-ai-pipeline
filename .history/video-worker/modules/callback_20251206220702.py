import requests
import logging

logger = logging.getLogger(__name__)

def send_callback(callback_url: str, result: dict):
    try:
        response = requests.post(callback_url, json=result, timeout=10)
        response.raise_for_status()
        logger.info(f"Callback sent successfully to {callback_url}")
    except Exception as e:
        logger.error(f"Failed to send callback: {str(e)}")