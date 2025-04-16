import os
import shutil
from typing import List
from app.helper.mediaserver import MediaServerHelper
from app.schemas import MediaServerConf, ServiceInfo
from app.log import logger
{
  "EmbyChecker": {
    "name": "EMBY媒体去重移动",
    "description": "识别电影文件并与 EMBY 媒体库对比，不存在则移动到指定目录。",
    "labels": "EMBY,去重,整理",
    "version": "1.0",
    "icon": "film.png",
    "author": "凹凸曼",
    "level": 2
  }
}
class Plugin:
    def __init__(self):
        self.mediainfo = MediaServerHelper()
        self.source_dir = "/source/films"
        self.target_dir = "/newfilms"

    def init_plugin(self, config: dict = None):
        # 可选：读取配置中路径
        if config:
            self.source_dir = config.get("source_dir", self.source_dir)
            self.target_dir = config.get("target_dir", self.target_dir)

        logger.info(f"[EMBY Checker] 开始扫描目录：{self.source_dir}")
        self.scan_and_move()

    def get_emby_titles(self) -> List[str]:
        """获取媒体服务器中的所有影片标题"""
        service = self.mediainfo.get_service(name="Emby")  # 假设服务名为Emby
        if not service:
            logger.warn("[EMBY Checker] 未找到媒体服务器服务 Emby")
            return []

        try:
            return service.instance.get_all_titles()  # 假设这个方法存在
        except Exception as e:
            logger.error(f"[EMBY Checker] 获取 EMBY 媒体库失败：{e}")
            return []

    def scan_and_move(self):
        """扫描目录文件并执行移动逻辑"""
        existing_titles = set(self.get_emby_titles())
        logger.info(f"[EMBY Checker] 媒体库已有 {len(existing_titles)} 个影片")

        for fname in os.listdir(self.source_dir):
            if not fname.lower().endswith(('.mp4', '.mkv', '.avi')):
                continue

            title = self.extract_title(fname)
            logger.info(f"[EMBY Checker] 检查影片：{title}")

            if title in existing_titles:
                logger.info(f"[EMBY Checker] 已存在：{title}，跳过")
                continue

            # 移动文件
            src = os.path.join(self.source_dir, fname)
            dst = os.path.join(self.target_dir, fname)
            try:
                shutil.move(src, dst)
                logger.info(f"[EMBY Checker] 移动文件：{fname} → {dst}")
            except Exception as e:
                logger.error(f"[EMBY Checker] 移动失败：{e}")

    def extract_title(self, filename: str) -> str:
        """从文件名中提取标题"""
        title = os.path.splitext(filename)[0]
        # 可在此添加更智能的解析逻辑，如去除年份、标清等
        return title.lower().strip()
