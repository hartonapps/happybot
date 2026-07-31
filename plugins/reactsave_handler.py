"""Handle reaction-based media saving."""
import logging
import os
from datetime import datetime

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
        
        msg = original_msg.get("message", {})
        if not msg or not isinstance(msg, dict):
            logger.warning(f"No message dict")
            return
        
        logger.info(f"Message keys: {list(msg.keys())}")
        
        # Check for media
        media_type = None
        media_obj = None
        caption = ""
        
        if "viewOnceMessage" in msg:
            logger.info("Detected viewOnceMessage")
            view_msg = msg["viewOnceMessage"].get("message", {})
            
            if "imageMessage" in view_msg:
                media_obj = view_msg["imageMessage"]
                media_type = "image"
                caption = media_obj.get("caption", "")
                logger.info(f"ViewOnce Image found")
                
            elif "videoMessage" in view_msg:
                media_obj = view_msg["videoMessage"]
                media_type = "video"
                caption = media_obj.get("caption", "")
                logger.info(f"ViewOnce Video found")
        
        elif "imageMessage" in msg:
            logger.info("Detected imageMessage")
            media_type = "image"
            media_obj = msg["imageMessage"]
            caption = media_obj.get("caption", "")
        
        elif "videoMessage" in msg:
            logger.info("Detected videoMessage")
            media_type = "video"
            media_obj = msg["videoMessage"]
            caption = media_obj.get("caption", "")
        
        elif "documentMessage" in msg:
            logger.info("Detected documentMessage")
            media_type = "document"
            media_obj = msg["documentMessage"]
            caption = media_obj.get("fileName", "")
        
        else:
            logger.info(f"No media detected. Message keys: {list(msg.keys())}")
            return
        
        if not media_obj:
            logger.warning(f"Media object is empty")
            return
        
        # Create media save directory
        save_dir = "saved_media"
        os.makedirs(save_dir, exist_ok=True)
        
        # Download media
        try:
            logger.info(f"Downloading {media_type} media...")
            media_buffer = await ctx.bot.download_media(original_msg)
            
            if not media_buffer:
                logger.error("Failed to download media")
                await ctx.send("❌ Failed to download media")
                return
            
            # Create filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = "jpg" if media_type == "image" else "mp4" if media_type == "video" else "pdf"
            filename = f"{save_dir}/{media_type}_{timestamp}.{ext}"
            
            # Save to file
            with open(filename, 'wb') as f:
                f.write(media_buffer)
            
            logger.info(f"✅ Media saved to {filename}")
            
            # Send saved media back to you
            owner_id = list(ctx.bot.owner_ids)[0] if ctx.bot.owner_ids else None
            if not owner_id:
                logger.error("No owner ID configured")
                return
            
            dm_chat_id = f"{owner_id}@s.whatsapp.net"
            
            # Send the media file
            await ctx.bot.send_media(
                dm_chat_id,
                filename,
                caption=f"📥 {media_type.upper()} saved\nEmoji: {ctx.event.text}\nFrom: {ctx.sender}\n{caption if caption else ''}"
            )
            
            logger.info(f"✅ Sent media to DM")
            
        except Exception as e:
            logger.exception(f"Error downloading media: {e}")
            await ctx.send(f"❌ Error: {str(e)}")
        
    except Exception as e:
        logger.exception(f"❌ Error in reaction handler: {e}")