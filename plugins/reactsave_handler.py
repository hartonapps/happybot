"""Handle reaction-based media saving."""
import logging

logger = logging.getLogger("reactsave_handler")

@bot.on("reaction")
async def on_reaction(ctx):
    """Extract and save media when someone reacts to a message."""
    try:
        # DEBUG: Log all reactions
        logger.info(f"REACTION RECEIVED: emoji={ctx.event.text}, from={ctx.sender}, enabled={ctx.db.get('reactsave_enabled', False)}")
        await ctx.send(f"✅ DEBUG: Reaction detected! Emoji: {ctx.event.text}, From: {ctx.sender}")
        
        # Check if reactsave is enabled
        if not ctx.db.get("reactsave_enabled", False):
            logger.info("ReactSave is disabled, ignoring reaction")
            await ctx.send("⚠️ ReactSave is disabled. Enable with: !reactsave on")
            return
        
        # Get the original message from raw event
        original_msg = ctx.event.raw
        if not original_msg:
            logger.warning("No raw message in event")
            await ctx.send("❌ Error: No original message data")
            return
        
        if "message" not in original_msg:
            logger.warning(f"No 'message' key in raw event. Keys: {list(original_msg.keys())}")
            await ctx.send(f"❌ Error: Message structure issue. Raw keys: {list(original_msg.keys())}")
            return
        
        msg = original_msg["message"]
        logger.info(f"Message keys: {list(msg.keys())}")
        
        # Check if it has media (viewonce, image, video, document, etc.)
        media_type = None
        actual_msg = None
        
        if "viewOnceMessage" in msg:
            media_type = "viewonce"
            actual_msg = msg["viewOnceMessage"].get("message", {})
            logger.info("Detected viewOnceMessage")
        elif "imageMessage" in msg:
            media_type = "image"
            actual_msg = msg
            logger.info("Detected imageMessage")
        elif "videoMessage" in msg:
            media_type = "video"
            actual_msg = msg
            logger.info("Detected videoMessage")
        elif "documentMessage" in msg:
            media_type = "document"
            actual_msg = msg
            logger.info("Detected documentMessage")
        else:
            logger.warning(f"No media found. Message keys: {list(msg.keys())}")
            await ctx.send(f"⚠️ No media detected in message. Message type: {list(msg.keys())}")
            return
        
        if not actual_msg:
            logger.warning("actual_msg is empty")
            await ctx.send("❌ Error: Could not extract message data")
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
        
        # Send success notification
        message = f"📥 {media_type.upper()} saved from {ctx.sender}"
        if caption:
            message += f"\n📝 Caption: {caption}"
        else:
            message += "\n(no caption)"
        
        logger.info(f"Sending notification: {message}")
        await ctx.send(message)
        
    except Exception as e:
        logger.exception(f"Error in reaction handler: {e}")
        try:
            await ctx.send(f"❌ ReactSave Error: {str(e)}")
        except:
            logger.error("Failed to send error message")