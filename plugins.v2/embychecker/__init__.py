"""
【智能媒体整理插件】
功能：自动识别电影文件夹、对比Emby媒体库、智能迁移未入库影片
"""
import os
import shutil
import requests
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType

class MediaOrganizer(_PluginBase):
    # 插件元信息
    plugin_name = "电影库管家"
    plugin_desc = "自动识别未入库电影并整理迁移"
    plugin_icon = "https://example.com/media_organizer.png"
    plugin_version = "1.2.0"
    author = "aotuman"
    author_url = "https://github.com/AOTUMAN133"
    # 插件配置项ID前缀
    plugin_config_prefix = "embychecker_"
    
    
    

    # 配置参数
    _enabled = False
    _onlyonce = False
    _cron = "0 2 * * *"
    _source_path = ""
    _target_path = ""
    _emby_url = "http://127.0.0.1:8096"
    _emby_api_key = ""
    _notify = True
    
    # 服务对象
    _scheduler: Optional[BackgroundScheduler] = None
    _emby_cache = {}
    _video_exts = ['.mkv', '.mp4', '.avi', '.mov']

    def init_plugin(self, config: dict = None):
        """初始化插件"""
        self.stop_service()
        
        if config:
            self._enabled = config.get("enabled", False)
            self._onlyonce = config.get("onlyonce", False)
            self._cron = config.get("cron", "0 2 * * *")
            self._source_path = config.get("source_path", "")
            self._target_path = config.get("target_path", "")
            self._emby_url = config.get("emby_url", "http://127.0.0.1:8096")
            self._emby_api_key = config.get("emby_api_key", "")
            self._notify = config.get("notify", True)

            # 立即执行模式
            if self._enabled and self._onlyonce:
                logger.info("电影库管家立即执行模式启动")
                self._start_organize()
                self._onlyonce = False
                self.update_config()

            # 定时任务设置
            if self._enabled and self._cron:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                try:
                    self._scheduler.add_job(
                        func=self._start_organize,
                        trigger=CronTrigger.from_crontab(self._cron),
                        name="电影库管家定时整理"
                    )
                except Exception as e:
                    logger.error(f"定时任务配置异常: {str(e)}")
                    self.systemmessage.put(f"定时配置错误: {e}")
                
                self._scheduler.start()
                logger.info("电影库管家定时服务已启动")

    def _start_organize(self):
        """整理流程入口"""
        # 验证配置
        if not self._validate_config():
            return

        # 加载Emby缓存
        self._load_emby_cache()

        # 处理电影文件
        result = self._process_movies()

        # 发送通知
        if self._notify:
            self._send_notification(result)

    def _validate_config(self) -> bool:
        """验证配置有效性"""
        errors = []
        if not os.path.isdir(self._source_path):
            errors.append("源目录无效")
        if not os.path.isdir(self._target_path):
            errors.append("目标目录无效")
        if not self._emby_api_key:
            errors.append("Emby API Key未配置")
        
        if errors:
            logger.error(f"配置验证失败: {'; '.join(errors)}")
            if self._notify:
                self.post_message(
                    mtype=NotificationType.Wechat if self._notify else None,
                    title="电影整理失败",
                    text=f"错误: {', '.join(errors)}"
                )
            return False
        return True

    def _load_emby_cache(self):
        """加载Emby媒体库数据"""
        try:
            headers = {"X-Emby-Token": self._emby_api_key}
            response = requests.get(
                f"{self._emby_url}/emby/Items",
                params={
                    "Recursive": "true",
                    "IncludeItemTypes": "Movie",
                    "Fields": "Path,Name,ProductionYear"
                },
                headers=headers
            )
            if response.status_code == 200:
                for item in response.json()["Items"]:
                    path = os.path.dirname(item.get("Path", ""))
                    self._emby_cache[path.lower()] = {
                        "name": item["Name"],
                        "year": item.get("ProductionYear")
                    }
                logger.info(f"成功加载 {len(self._emby_cache)} 个Emby电影记录")
            else:
                logger.error(f"Emby请求失败: {response.status_code}")
        except Exception as e:
            logger.error(f"加载Emby缓存异常: {str(e)}")

    def _process_movies(self) -> Dict:
        """处理电影文件夹"""
        result = {
            "total": 0,
            "moved": 0,
            "skipped": 0,
            "failed": 0,
            "details": []
        }

        for entry in os.scandir(self._source_path):
            if entry.is_dir():
                movie_info = self._analyze_movie_folder(entry.path)
                if movie_info:
                    result["total"] += 1
                    process_result = self._handle_movie_folder(entry.path, movie_info)
                    result["details"].append(process_result)
                    if process_result["status"] == "moved":
                        result["moved"] += 1
                    else:
                        result[process_result["status"]] +=1
        return result

    def _analyze_movie_folder(self, folder_path: str) -> Optional[Dict]:
        """分析电影文件夹"""
        # 识别视频文件
        video_files = [
            f for f in Path(folder_path).rglob('*') 
            if f.suffix.lower() in self._video_exts
        ]
        if not video_files:
            return None

        # 提取元数据（示例逻辑）
        folder_name = os.path.basename(folder_path)
        return {
            "path": folder_path,
            "name": folder_name.split('(').strip(),
            "year": self._extract_year(folder_name)
        }

    def _extract_year(self, text: str) -> Optional[int]:
        """从文件名提取年份"""
        try:
            # 匹配 (2023) 或 2023 格式
            for part in text.replace(']', '').replace(')', ' ').split():
                if len(part) == 4 and part.isdigit():
                    year = int(part)
                    if 1900 < year < 2100:
                        return year
        except:
            pass
        return None

    def _handle_movie_folder(self, folder_path: str, movie_info: Dict) -> Dict:
        """处理单个电影文件夹"""
        # 检查是否已存在
        emby_record = self._emby_cache.get(os.path.dirname(folder_path).lower())
        if emby_record:
            return {
                "name": movie_info["name"],
                "status": "skipped",
                "reason": "已存在于媒体库"
            }

        # 执行移动操作
        target_path = os.path.join(self._target_path, os.path.basename(folder_path))
        try:
            shutil.move(folder_path, target_path)
            logger.info(f"成功移动: {folder_path} -> {target_path}")
            return {
                "name": movie_info["name"],
                "status": "moved",
                "path": target_path
            }
        except Exception as e:
            logger.error(f"移动失败: {folder_path} - {str(e)}")
            return {
                "name": movie_info["name"],
                "status": "failed",
                "reason": str(e)
            }

    def _send_notification(self, result: Dict):
        """发送整理报告"""
        if not result["total"]:
            return

        text = f"""整理完成：
        ▪ 总数：{result["total"]}
        ▪ 已迁移：{result["moved"]}
        ▪ 已存在：{result["skipped"]}
        ▪ 失败：{result["failed"]}"""
        
        if result["failed"] > 0:
            failures = "\n".join([f"{d['name']}：{d['reason']}" 
                                for d in result["details"] if d["status"] == "failed"])
            text += f"\n失败详情：\n{failures}"

        self.post_message(
            mtype=NotificationType.Wechat if self._notify else None,
            title="电影整理报告",
            text=text
        )

    def get_form(self) -> Tuple[List[Dict], Dict]:
        """配置表单"""
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            self._switch("enabled", "启用插件"),
                            self._switch("onlyonce", "立即运行一次"),
                            self._switch("notify", "发送通知")
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self._input("cron", "定时周期", placeholder="0 2 * * *"),
                            self._input("source_path", "源目录", required=True),
                            self._input("target_path", "目标目录", required=True)
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self._input("emby_url", "Emby地址", required=True),
                            self._input("emby_api_key", "Emby API密钥", required=True)
                        ]
                    }
                ]
            }
        ], {
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "source_path": self._source_path,
            "target_path": self._target_path,
            "emby_url": self._emby_url,
            "emby_api_key": self._emby_api_key,
            "notify": self._notify
        }

    def stop_service(self):
        """停止服务"""
        if self._scheduler:
            self._scheduler.remove_all_jobs()
            if self._scheduler.running:
                self._scheduler.shutdown()
            self._scheduler = None
