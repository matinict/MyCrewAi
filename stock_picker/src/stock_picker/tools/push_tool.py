from crewai.tools import BaseTool
from typing import Type, Any
from pydantic import BaseModel, Field
import os
import requests


class PushNotificationInput(BaseModel):
    """Input schema for push notification"""
    message: str = Field(..., description="The message to be sent to the user.")


class PushNotificationTool(BaseTool):  
    name: str = "Send a Push Notification"
    description: str = (
        "This tool is used to send a push notification to the user. "
        "Use this to notify the user about important decisions or updates."
    )
    args_schema: Type[BaseModel] = PushNotificationInput

    def _run(self, message: str) -> str:
        """Send a push notification to the user"""
        # Handle case where message might be passed as dict
        if isinstance(message, dict):
            message = message.get('message', str(message))
        
        pushover_user = os.getenv("PUSHOVER_USER")
        pushover_token = os.getenv("PUSHOVER_TOKEN")
        
        # Only send if credentials are set
        if pushover_user and pushover_token:
            pushover_url = "https://api.pushover.net/1/messages.json"
            payload = {
                "user": pushover_user, 
                "token": pushover_token, 
                "message": message
            } 
            try:
                response = requests.post(pushover_url, data=payload)
                print(f"✓ Push notification sent: {message[:100]}...")
                return f"Notification sent successfully: {message}"
            except Exception as e:
                print(f"✗ Failed to send push notification: {e}")
                return f"Failed to send notification: {str(e)}"
        else:
            print(f"ℹ Push notification (not sent - no credentials): {message}")
            return f"Notification logged (credentials not set): {message}"