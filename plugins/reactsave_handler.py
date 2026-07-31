"""Handle reaction-based media saving."""
import logging

logger = logging.getLogger("reactsave_handler")

@bot.on("reaction")
async def on_reaction(ctx):
    """Extract and save media when someone reacts to a message."""
    try:
        # DEBUG: Log all reactions
        logger.info(f"REACTION RECEIVED: emoji={ctx.event.text}, from={ctx.sender}")
        
        # Check if reactsave is enabled
        if not ctx.db.get("reactsave_enabled", False):
            logger.info("ReactSave is disabled, ignoring reaction")
            return
        
        # Get the original message from raw event
        original_msg = ctx.event.raw
        if not original_msg:
            logger.warning("No raw message in event")
            return
        
        # Handle the message structure - raw is the full message object
        msg = original_msg.get("message") or original_msg
        
        if not msg:
            logger.warning(f"No message data. Raw keys: {list(original_msg.keys()) if isinstance(original_msg, dict) else 'not a dict'}")
            return
        
        if not isinstance(msg, dict):
            logger.warning(f"Message is not a dict, it's {type(msg)}")
            return
        
        logger.info(f"Message keys: {list(msg.keys())}")
        
        # Check if it has media (viewonce, image, video, document, etc.)
        media_type = None
        actual_msg = None
        has_media = False
        
        if "viewOnceMessage" in msg:
            media_type = "viewonce"
            actual_msg = msg["viewOnceMessage"].get("message", {})
            has_media = True
            logger.info("Detected viewOnceMessage")
        elif "imageMessage" in msg:
            media_type = "image"
            actual_msg = msg
            has_media = True
            logger.info("Detected imageMessage")
        elif "videoMessage" in msg:
            media_type = "video"
            actual_msg = msg
            has_media = True
            logger.info("Detected videoMessage")
        elif "documentMessage" in msg:
            media_type = "document"
            actual_msg = msg
            has_media = True
            logger.info("Detected documentMessage")
        else:
            logger.warning(f"No media found. Message keys: {list(msg.keys())}")
            return
        
        if not has_media or not actual_msg:
            logger.warning("No media or actual_msg is empty")
            return
        
        # Extract caption if available
        caption = ""
        try:
            if "imageMessage" in actual_msg:
                caption = actual_msg["imageMessage"].get("caption", "")
            elif "videoMessage" in actual_msg:
                caption = actual_msg["videoMessage"].get("caption", "")
            elif "viewOnceMessage" in msg:
                # For viewonce, try to get caption from inside
                view_msg = msg["viewOnceMessage"].get("message", {})
                if "imageMessage" in view_msg:
                    caption = view_msg["imageMessage"].get("caption", "")
                elif "videoMessage" in view_msg:
                    caption = view_msg["videoMessage"].get("caption", "")
        except Exception as e:
            logger.error(f"Error extracting caption: {e}")
        
        # Get owner's personal chat ID (DM with yourself)
        owner_id = list(ctx.bot.owner_ids)[0] if ctx.bot.owner_ids else None
        if not owner_id:
            logger.error("No owner ID configured")
            return
        
        # Convert owner ID to WhatsApp format for DM
        dm_chat_id = f"{owner_id}@s.whatsapp.net"
        
        # Send notification to YOURSELF, not the chat
        message = f"📥 {media_type.upper()} saved from {ctx.sender}\n"
        if caption:
            message += f"📝 Caption: {caption}"
        else:
            message += "(no caption)"
        
        logger.info(f"Sending to DM {dm_chat_id}: {message}")
        # Send to your own DM, not ctx.send (which sends to reaction chat)
        await ctx.bot.send_message(dm_chat_id, message)
        
    except Exception as e:
        logger.exception(f"Error in reaction handler: {e}")