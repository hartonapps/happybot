"""Handle reaction-based media saving."""
import logging

logger = logging.getLogger("reactsave_handler")

@bot.on("reaction")
async def on_reaction(ctx):
    """Extract and save media when someone reacts to a message."""
    try:
        logger.info(f"REACTION RECEIVED: emoji={ctx.event.text}, from={ctx.sender}")
        
        # Check if reactsave is enabled
        if not ctx.db.get("reactsave_enabled", False):
            logger.info("ReactSave is disabled")
            return
        
        # Get the original message
        original_msg = ctx.event.raw
        if not original_msg or not isinstance(original_msg, dict):
            logger.warning(f"Invalid raw message: {original_msg}")
            return
        
        # Message is inside original_msg.message
        msg = original_msg.get("message", {})
        if not msg or not isinstance(msg, dict):
            logger.warning(f"No message dict. Got: {msg}")
            return
        
        logger.info(f"Message keys: {list(msg.keys())}")
        
        # Check for media
        media_type = None
        media_obj = None
        
        if "viewOnceMessage" in msg:
            media_type = "🔐 ViewOnce"
            view_msg = msg["viewOnceMessage"].get("message", {})
            if "imageMessage" in view_msg:
                media_obj = view_msg["imageMessage"]
            elif "videoMessage" in view_msg:
                media_obj = view_msg["videoMessage"]
        elif "imageMessage" in msg:
            media_type = "🖼️ Image"
            media_obj = msg["imageMessage"]
        elif "videoMessage" in msg:
            media_type = "🎥 Video"
            media_obj = msg["videoMessage"]
        elif "documentMessage" in msg:
            media_type = "📄 Document"
            media_obj = msg["documentMessage"]
        elif "audioMessage" in msg:
            media_type = "🎵 Audio"
            media_obj = msg["audioMessage"]
        else:
            logger.info(f"No media detected. Message keys: {list(msg.keys())}")
            return
        
        if not media_obj:
            logger.warning("Media object is empty")
            return
        
        # Extract caption
        caption = media_obj.get("caption", "")
        
        # Get owner ID for DM
        owner_id = list(ctx.bot.owner_ids)[0] if ctx.bot.owner_ids else None
        if not owner_id:
            logger.error("No owner ID configured")
            return
        
        dm_chat_id = f"{owner_id}@s.whatsapp.net"
        
        # Send notification
        message = f"📥 {media_type} saved - Reacted: {ctx.event.text}"
        if caption:
            message += f"\n📝 Caption: {caption}"
        
        logger.info(f"Sending to DM: {message}")
        await ctx.bot.send_message(dm_chat_id, message)
        
    except Exception as e:
        logger.exception(f"Error in reaction handler: {e}")