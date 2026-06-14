import logging
from typing import Tuple

logger = logging.getLogger(__name__)


class ResponseHandler:
    def __init__(self, ai_client, db):
        self.ai = ai_client
        self.db = db

    async def process_response(self, lead_id: int, response_text: str, channel: str) -> Tuple[str, str]:
        system_prompt = """You are an AI sales assistant. Analyze the prospect's response and determine:
        1. Intent: positive, negative, neutral, or meeting_request
        2. Generate an appropriate reply
        
        Be helpful, not pushy. Never spam."""

        user_prompt = f"""Analyze this {channel} response and reply appropriately:
        
        Response: "{response_text}"
        
        Classify as: positive (interested), negative (not interested), neutral (need more info), or meeting_request (wants call/meeting).
        
        If positive/meeting_request: Suggest next steps and propose scheduling.
        If negative: Thank them politely, leave door open for future.
        If neutral: Answer their questions and try to move toward call.
        
        Keep response under 150 words."""

        ai_reply = await self.ai.generate(user_prompt, system_prompt)
        intent = self._classify_intent(response_text, ai_reply)

        if channel == "email":
            await self.db.log_response(lead_id, "email_reply", response_text)
        
        if intent == "positive" or intent == "meeting_request":
            await self.db.update_lead_status(lead_id, "qualified")
        elif intent == "negative":
            await self.db.update_lead_status(lead_id, "unqualified")

        return intent, ai_reply

    def _classify_intent(self, response: str, ai_reply: str) -> str:
        response_lower = response.lower()
        
        positive_words = ["interested", "sounds good", "tell me more", "yes", "call", "meeting", "schedule"]
        negative_words = ["not interested", "no thanks", "stop", "unsubscribe"]
        meeting_words = ["call", "meeting", "schedule", "available", "time", "discuss"]
        
        if any(word in response_lower for word in negative_words):
            return "negative"
        if any(word in response_lower for word in meeting_words) or "?" in response:
            return "meeting_request"
        if any(word in response_lower for word in positive_words):
            return "positive"
        return "neutral"


class ConversationManager:
    def __init__(self, ai_client, db):
        self.ai = ai_client
        self.db = db

    async def generate_reply(self, lead_id: int, incoming_message: str, context: dict) -> str:
        lead = await self.db.get_lead_by_id(lead_id)
        
        system_prompt = f"""You are {context.get('your_name', 'Sales Rep')} from {context.get('agency_name', 'Digital Marketing Agency')}.
        Write a natural, conversational reply to a prospect inquiry.
        Reference previous conversations if any.
        Stay professional but approachable."""

        user_prompt = f"""Inbound message from {lead.get('contact_name', 'prospect')} at {lead.get('company_name', 'company')}:
        
        "{incoming_message}"
        
        Company: {lead.get('company_name')}
        Industry: {lead.get('industry')}
        Location: {lead.get('location')}
        
        Your goal: Move them toward booking a 15-min discovery call.
        Ask clarifying questions if needed.
        Keep it conversational (under 100 words)."""

        return await self.ai.generate(user_prompt, system_prompt)