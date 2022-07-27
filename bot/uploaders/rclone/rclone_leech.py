from configparser import ConfigParser
from os import walk
import os
from random import randrange
import re
import time
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot import GLOBAL_RCLONE, LOGGER, TG_SPLIT_SIZE, Bot, app
from bot.core.get_vars import get_val
from bot.uploaders.telegram.telegram_uploader import TelegramUploader
from bot.utils.bot_utils.misc_utils import clean_path, get_rclone_config, get_readable_size
from bot.utils.bot_utils.zip_utils import split_in_zip
import subprocess
import asyncio
from bot.utils.status_util.bottom_status import get_bottom_status



class RcloneLeech:
    def __init__(self, user_msg, chat_id, origin_dir, dest_dir, folder= False, path= "") -> None:
        self.id = self.__create_id(8)
        self.__client = app if app is not None else Bot
        self.__user_msg = user_msg
        self.__chat_id = chat_id
        self.__origin_dir = origin_dir
        self.cancel = False
        self.__folder= folder
        self.__path= path
        self.__dest_dir = dest_dir

    def __create_id(self, count):
        map = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        id = ''
        i = 0
        while i < count:
            rnd = randrange(len(map))
            id += map[rnd]
            i += 1
        return id

    async def leech(self):
        GLOBAL_RCLONE.add(self)
        await self.__user_msg.edit("Preparing for download...")
        origin_drive = get_val("DEFAULT_RCLONE_DRIVE")
        tg_split_size= get_readable_size(TG_SPLIT_SIZE) 
        conf_path = await get_rclone_config()
        conf = ConfigParser()
        conf.read(conf_path)
        drive_name = ""

        for i in conf.sections():
            if origin_drive == str(i):
                if conf[i]["type"] == "drive":
                    LOGGER.info("G-Drive Download Detected.")
                else:
                    drive_name = conf[i]["type"]
                    LOGGER.info(f"{drive_name} Download Detected.")
                break

        rclone_copy_cmd = [
            'rclone', 'copy', f'--config={conf_path}', f'{origin_drive}:{self.__origin_dir}', f'{self.__dest_dir}', '-P']

        self.__rclone_pr = subprocess.Popen(
            rclone_copy_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        rcres= await self.__rclone_update()

        if rcres == False:
            self.__rclone_pr.kill()
            await self.__user_msg.edit("Leech cancelled")
            GLOBAL_RCLONE.remove(self)
            return 

        if self.__folder:
            for dirpath, _, filenames in walk(self.__dest_dir):
                if len(filenames) == 0:continue 
                sorted_fn= sorted(filenames)
                for i, file in enumerate(sorted_fn):  
                    timer = 60  
                    if i < 25:
                        timer = 5
                    if i < 50 and i > 25:
                        timer = 10
                    if i < 100 and i > 50:
                        timer = 15
                    if i < 150 and i > 100:
                        timer = 20
                    if i < 200 and i > 150:
                        timer = 25
                    f_path = os.path.join(dirpath, file)
                    f_size = os.path.getsize(f_path)
                    if int(f_size) > TG_SPLIT_SIZE:
                        message= await self.__client.send_message(self.__chat_id, f"File larger than {tg_split_size}, Splitting...")     
                        split_dir= await split_in_zip(f_path, size=TG_SPLIT_SIZE) 
                        os.remove(f_path) 
                        dir_list= os.listdir(split_dir)
                        dir_list.sort() 
                        for file in dir_list :
                            f_path = os.path.join(split_dir, file)
                            try:
                                await TelegramUploader(f_path, message, self.__chat_id).upload()
                            except FloodWait as fw:
                                await asyncio.sleep(fw.seconds + 5)
                                await TelegramUploader(f_path, message, self.__chat_id).upload()
                            time.sleep(timer)
                    else:
                        try:
                            await TelegramUploader(f_path, self.__user_msg, self.__chat_id).upload()
                        except FloodWait as fw:
                            await asyncio.sleep(fw.seconds + 5)
                            await TelegramUploader(f_path, self.__user_msg, self.__chat_id).upload()
                        time.sleep(timer)
            clean_path(self.__dest_dir)
            await self.__client.send_message(self.__chat_id, "Nothing else to upload!")  
        else:
            f_path = os.path.join(self.__dest_dir, self.__path)
            f_size = os.path.getsize(f_path)
            if int(f_size) > TG_SPLIT_SIZE:
                message= await self.__client.send_message(self.__chat_id, f"File larger than {tg_split_size}, Splitting...")     
                split_dir= await split_in_zip(f_path, size=TG_SPLIT_SIZE) 
                os.remove(f_path) 
                dir_list= os.listdir(split_dir)
                dir_list.sort() 
                for file in dir_list :
                    timer = 5
                    f_path = os.path.join(split_dir, file, )
                    try:
                        await TelegramUploader(f_path, message, self.__chat_id).upload()
                    except FloodWait as fw:
                        await asyncio.sleep(fw.seconds + 5)
                        await TelegramUploader(f_path, message, self.__chat_id).upload()
                    time.sleep(timer)
                await self.__client.send_message(self.__chat_id, "Nothing else to upload!")
            else:
                try:    
                    await TelegramUploader(f_path, self.__user_msg, self.__chat_id).upload()
                except FloodWait as fw:
                    await asyncio.sleep(fw.seconds + 5)
                    await TelegramUploader(f_path, message, self.__chat_id).upload()
            clean_path(self.__dest_dir)    
        GLOBAL_RCLONE.remove(self)

    async def __rclone_update(self):
        blank = 0
        process = self.__rclone_pr
        user_message = self.__user_msg
        sleeps = False
        start = time.time()
        edit_time = get_val('EDIT_SLEEP_SECS')
        msg = ''
        msg1 = ''
        while True:
            data = process.stdout.readline().decode()
            data = data.strip()
            mat = re.findall('Transferred:.*ETA.*', data)
            
            if mat is not None and len(mat) > 0:
                sleeps = True
                nstr = mat[0].replace('Transferred:', '')
                nstr = nstr.strip()
                nstr = nstr.split(',')
                percent = nstr[1].strip('% ')
                try:
                    percent = int(percent)
                except:
                    percent = 0
                prg = self.__progress_bar(percent)
                
                msg = '**Name:** `{}`\n**Status:** {}\n{}\n**Downloaded:** {}\n**Speed:** {} | **ETA:** {}\n'.format(os.path.basename(self.__path), 'Downloading...', prg, nstr[0], nstr[2], nstr[3].replace('ETA', ''))
                msg += get_bottom_status() 
                
                if time.time() - start > edit_time:
                    if msg1 != msg:
                        start = time.time()
                        try:
                            await user_message.edit(text=msg, reply_markup=(InlineKeyboardMarkup([
                            [InlineKeyboardButton('Cancel', callback_data=(f"cancel_rclone_{self.id}".encode('UTF-8')))]
                            ])))    
                        except:
                            pass                        
                        msg1 = msg
                
            if data == '':
                blank += 1
                if blank == 20:
                    break
            else:
                blank = 0

            if sleeps:
                sleeps = False
                if self.cancel:
                    return False
                await asyncio.sleep(2)
                process.stdout.flush()
    
    def __progress_bar(self, percentage):
        comp ="▪️"
        ncomp ="▫️"
        pr = ""

        try:
            percentage=int(percentage)
        except:
            percentage = 0

        for i in range(1, 11):
            if i <= int(percentage/10):
                pr += comp
            else:
                pr += ncomp
        return pr