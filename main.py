"""
GitHub Star Manager Plugin for AstrBot
基于 AstrBot_Plugins_Collection 的 plugins.json 数据源的插件管理器
"""

import asyncio
import json
from typing import List, Dict, Optional
from dataclasses import dataclass, field
import re
from functools import wraps

import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig, logger

def require_permission(func):
    """
    权限检查装饰器
    用于统一处理命令方法的权限检查
    
    Args:
        func: 需要权限检查的方法
        
    Returns:
        装饰后的方法
    """
    @wraps(func)
    async def wrapper(self, event: AstrMessageEvent, *args, **kwargs):
        if not self._check_permission(event.get_sender_id()):
            yield event.plain_result("❌ 权限不足，请联系管理员")
            return
        
        # 如果权限检查通过，调用原方法
        async for result in func(self, event, *args, **kwargs):
            yield result
    
    return wrapper

# 自定义异常类
class GitHubAPIError(Exception):
    """GitHub API错误基类"""
    pass

class AuthenticationError(GitHubAPIError):
    """认证错误"""
    pass

class RepositoryNotFoundError(GitHubAPIError):
    """仓库不存在错误"""
    pass

class RateLimitError(GitHubAPIError):
    """API限流错误"""
    pass

class NetworkError(GitHubAPIError):
    """网络错误"""
    pass

class NotStarredError(GitHubAPIError):
    """仓库未被star错误"""
    pass

class PermissionError(GitHubAPIError):
    """权限不足错误（Token缺少必要的scope或访问被禁止）"""
    pass

@dataclass
class PluginInfo:
    """
    插件信息数据类
    存储从plugins.json解析出的插件基本信息
    
    特性：
    - 使用dataclasses.field(default_factory=list)正确处理可变默认参数
    - 自动生成短名称（_generate_short_name）
    - 支持灵活的数据格式适配
    - 符合Python 3.10+的现代编程惯例
    """
    name: str              # 插件名称
    author: str            # 作者名
    description: str       # 插件描述
    repo_url: str          # GitHub仓库地址
    stars: int = 0         # Star数量
    language: str = "Python"  # 编程语言
    tags: List[str] = field(default_factory=list)  # 标签列表
    short_name: str = ""   # 短名称/别名
    plugin_id: int = 0     # 插件ID（用于快速引用）
    
    def __post_init__(self):
        if not self.short_name:
            # 自动生成短名称
            self.short_name = self._generate_short_name()
    
    def _generate_short_name(self) -> str:
        """
        生成插件短名称
        
        Returns:
            str: 生成的短名称
        """
        # 移除常见前缀
        name = self.name
        prefixes = ["astrbot_plugin_", "astrbot_", "plugin_"]
        for prefix in prefixes:
            if name.lower().startswith(prefix):
                name = name[len(prefix):]
                break
        
        # 限制长度
        if len(name) > 15:
            name = name[:15]
        
        return name

class GitHubAPIClient:
    """
    GitHub API客户端
    负责处理所有GitHub API交互，包括获取仓库信息和点star操作
    
    主要功能：
    - verify_token(): 验证GitHub Token有效性
    - get_repository_info(): 获取仓库基本信息
    - star_repository(): 给仓库点star
    - test_connectivity(): 测试GitHub API连通性（使用现代事件循环API）
    - update_plugin_stars(): 实时更新插件star数
    
    网络安全特性：
    - 使用HTTP头检查速率限制（X-RateLimit-Remaining）
    - 精确区分仓库不存在和未star的情况
    - 精确的403错误分类（区分Token认证失败和权限不足）
    - 模块化的错误处理（_parse_403_error方法）
    - 具体的异常处理（避免过于宽泛的异常捕获）
    - 现代的异步编程实践（asyncio.get_running_loop）
    
    核心方法：
    - _parse_403_error(): 精确解析403错误响应，避免歧义
    - _make_request(): 统一的HTTP请求处理和错误分类
    
    异常类型：
    - AuthenticationError: Token认证失败（Token无效或过期）
    - PermissionError: 权限不足（Token缺少必要scope或访问被禁止）
    - RepositoryNotFoundError: 仓库不存在
    - RateLimitError: API限流
    - NotStarredError: 仓库未被star
    - NetworkError: 网络错误
    """
    
    def __init__(self, token: str, config: dict):
        """
        初始化GitHub API客户端
        
        Args:
            token: GitHub Personal Access Token
            config: 插件配置字典
        """
        self.token = token
        self.config = config
        
        # API端点配置 
        self.api_base_url = "https://api.github.com"
        
        # 网络配置
        self.timeout = config.get('api_settings', {}).get('request_timeout', 20)
        self.max_retries = config.get('api_settings', {}).get('max_retries', 3)
    
    def _parse_403_error(self, response_text: str) -> tuple[str, str]:
        """
        解析403错误响应体，返回错误类型和消息
        
        Args:
            response_text: HTTP响应体文本
            
        Returns:
            tuple: (错误类型, 错误消息)
                  错误类型: "rate_limit", "authentication", "permission"
        """
        if not response_text:
            return "permission", "权限不足"
        
        response_lower = response_text.lower()
        
        # 检查速率限制
        if "rate limit" in response_lower or "api rate limit" in response_lower:
            return "rate_limit", "GitHub API请求频率超限"
        
        # 检查Token认证问题
        if "bad credentials" in response_lower or "invalid token" in response_lower:
            return "authentication", "GitHub Token无效或已过期"
        
        # 检查Token权限范围问题
        if "insufficient" in response_lower or "scope" in response_lower:
            return "permission", "GitHub Token缺少必要的权限范围（如public_repo）"
        
        # 检查访问被禁止
        if "forbidden" in response_lower or "access denied" in response_lower:
            return "permission", "访问被禁止，请检查仓库可见性或Token权限"
        
        # 尝试解析JSON响应获取更详细的错误信息
        try:
            error_data = json.loads(response_text)
            if "message" in error_data:
                return "permission", f"权限不足: {error_data['message']}"
        except (json.JSONDecodeError, KeyError):
            pass
        
        # 默认作为权限问题
        return "permission", "权限不足"
    
    async def _make_request(self, method: str, url: str, **kwargs) -> dict:
        """
        执行HTTP请求
        
        Args:
            method: HTTP方法
            url: 请求URL
            **kwargs: 额外请求参数
            
        Returns:
            dict: 响应JSON数据
            
        Raises:
            AuthenticationError: Token认证失败（Token无效或过期）
            PermissionError: 权限不足（Token缺少必要scope或访问被禁止）
            RepositoryNotFoundError: 仓库不存在
            RateLimitError: API限流
            NetworkError: 网络错误
        """
        headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AstrBot-GitHub-Star-Plugin/1.0"
        }
        
        session_kwargs = {
            'headers': headers,
            'timeout': aiohttp.ClientTimeout(total=self.timeout)
        }
        
        async with aiohttp.ClientSession(**session_kwargs) as session:
            async with session.request(method, url, **kwargs) as response:
                if response.status == 401:
                    raise AuthenticationError("GitHub token无效或已过期")
                elif response.status == 404:
                    raise RepositoryNotFoundError("仓库不存在或无权访问") 
                elif response.status == 403:
                    # 优先检查HTTP头中的速率限制信息
                    rate_limit_remaining = response.headers.get('X-RateLimit-Remaining', None)
                    if rate_limit_remaining == '0':
                        raise RateLimitError("GitHub API请求频率超限")
                    
                    # 获取响应体并解析错误类型
                    error_type = "permission"  # 默认为权限问题
                    error_message = "权限不足"
                    
                    try:
                        response_text = await response.text()
                        error_type, error_message = self._parse_403_error(response_text)
                        
                        # 如果解析出是速率限制，直接抛出对应异常
                        if error_type == "rate_limit":
                            raise RateLimitError(error_message)
                        
                    except (aiohttp.ClientError, UnicodeDecodeError, aiohttp.ClientPayloadError) as e:
                        logger.debug(f"无法解析403响应体: {e}")
                        # 使用默认值
                    
                    # 根据解析结果抛出相应的异常
                    if error_type == "authentication":
                        raise AuthenticationError(error_message)
                    else:
                        raise PermissionError(error_message)
                elif response.status not in [200, 204]:  # 204 No Content也表示成功
                    raise NetworkError(f"HTTP错误: {response.status}")
                
                if response.content_type == 'application/json':
                    return await response.json()
                else:
                    return {"status": "success"}
    
    async def verify_token(self) -> bool:
        """
        验证GitHub Token有效性
        
        Returns:
            bool: Token是否有效
        """
        try:
            await self._make_request("GET", f"{self.api_base_url}/user")
            return True
        except AuthenticationError as e:
            logger.error(f"Token认证失败: {e}")
            return False
        except PermissionError as e:
            logger.error(f"Token权限不足: {e}")
            return False
        except (RateLimitError, NetworkError) as e:
            logger.error(f"Token验证时网络错误: {e}")
            return False
        except Exception as e:
            logger.error(f"Token验证发生意外错误: {e}")
            return False
    
    async def get_repository_info(self, owner: str, repo: str) -> dict:
        """
        获取仓库基本信息
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            
        Returns:
            dict: 仓库信息
        """
        url = f"{self.api_base_url}/repos/{owner}/{repo}"
        return await self._make_request("GET", url)
    
    async def star_repository(self, owner: str, repo: str) -> bool:
        """
        给仓库点star
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            
        Returns:
            bool: 是否成功
        """
        url = f"{self.api_base_url}/user/starred/{owner}/{repo}"
        try:
            await self._make_request("PUT", url)
            return True
        except AuthenticationError as e:
            logger.error(f"点star失败（认证错误）: {e}")
            return False
        except PermissionError as e:
            logger.error(f"点star失败（权限不足）: {e}")
            return False
        except RepositoryNotFoundError as e:
            logger.error(f"点star失败（仓库不存在）: {e}")
            return False
        except (RateLimitError, NetworkError) as e:
            logger.error(f"点star失败（网络错误）: {e}")
            return False
        except Exception as e:
            logger.error(f"点star发生意外错误: {e}")
            return False
    
    async def check_star_status(self, owner: str, repo: str) -> bool:
        """
        检查是否已点star
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            
        Returns:
            bool: 是否已点star
            
        Raises:
            RepositoryNotFoundError: 仓库不存在或无权访问
            NotStarredError: 仓库存在但未被star
            NetworkError: 网络连接错误
        """
        # 首先检查仓库是否存在
        try:
            await self.get_repository_info(owner, repo)
        except RepositoryNotFoundError:
            # 仓库不存在
            raise
        
        # 然后检查star状态
        url = f"{self.api_base_url}/user/starred/{owner}/{repo}"
        try:
            await self._make_request("GET", url)
            return True
        except RepositoryNotFoundError:
            # 仓库存在但未star
            raise NotStarredError("仓库未被star")
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning(f"检查star状态时网络错误: {e}")
            raise NetworkError("网络连接失败，无法检查star状态") from e
        except Exception as e:
            logger.error(f"检查star状态时发生意外错误: {e}")
            raise
    
    def _parse_repo_url(self, url: str) -> tuple:
        """
        解析GitHub仓库URL获取owner和repo
        
        Args:
            url: GitHub仓库URL
            
        Returns:
            tuple: (owner, repo)或(None, None)
        """
        if not url:
            return None, None
            
        patterns = [
            r'github\.com/([^/]+)/([^/\s]+)',
            r'github\.com/([^/]+)/([^/\s]+)\.git',
            r'github\.com/([^/]+)/([^/\s]+)/.*'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1), match.group(2)
        
        return None, None
    
    async def test_connectivity(self) -> Dict[str, Dict[str, any]]:
        """
        测试GitHub API的连通性
        
        Returns:
            Dict: API连通性测试结果
        """
        results = {}
        
        loop = asyncio.get_running_loop()
        start_time = loop.time()
        try:
            # 测试基本连接
            test_url = f"{self.api_base_url}/rate_limit"  # GitHub API的轻量级端点
            await self._make_request("GET", test_url)
            
            latency = round((loop.time() - start_time) * 1000)  # 毫秒
            results[self.api_base_url] = {
                'success': True,
                'latency': latency,
                'error': None
            }
            
        except Exception as e:
            latency = round((loop.time() - start_time) * 1000)
            results[self.api_base_url] = {
                'success': False,
                'latency': latency,
                'error': str(e)
            }
        
        return results
    
    async def update_plugin_stars(self, plugin: PluginInfo) -> PluginInfo:
        """
        实时更新插件的star数
        
        Args:
            plugin: 插件信息对象
            
        Returns:
            PluginInfo: 更新后的插件信息
        """
        owner, repo = self._parse_repo_url(plugin.repo_url)
        if owner and repo:
            try:
                repo_info = await self.get_repository_info(owner, repo)
                plugin.stars = repo_info.get('stargazers_count', plugin.stars)
                logger.debug(f"更新插件 {plugin.name} star数: {plugin.stars}")
            except Exception as e:
                logger.debug(f"获取插件 {plugin.name} star数失败: {e}")
                # 保持原有star数
        return plugin

class PluginDatabase:
    """
    插件数据库管理器
    负责从AstrBot_Plugins_Collection加载和管理插件数据
    """
    
    def __init__(self):
        """初始化插件数据库"""
        self.plugins: List[PluginInfo] = []
        self.last_update = 0
        self.cache_ttl = 3600  # 1小时缓存
    
    async def load_plugins_from_collection(self) -> bool:
        """
        从AstrBot_Plugins_Collection加载插件数据
        
        Returns:
            bool: 是否加载成功
        """
        # 修复：移除无效URL，只保留有效的GitHub Raw URL
        urls = [
            "https://raw.githubusercontent.com/AstrBotDevs/AstrBot_Plugins_Collection/main/plugins.json",
            "https://cdn.jsdelivr.net/gh/AstrBotDevs/AstrBot_Plugins_Collection@main/plugins.json"  # CDN备选
        ]
        
        for url in urls:
            try:
                logger.info(f"从 {url} 加载插件数据...")
                
                timeout = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as response:
                        response.raise_for_status()
                        
                        # 修复：手动解析JSON，不依赖Content-Type
                        text_content = await response.text()
                        data = json.loads(text_content)
                        
                        self.plugins = []
                        
                        # 处理字典格式的插件数据
                        if isinstance(data, dict):
                            for plugin_name, plugin_info in data.items():
                                # 添加插件名到插件信息中
                                plugin_info['name'] = plugin_name
                                plugin = self._parse_plugin_data(plugin_info)
                                if plugin:
                                    self.plugins.append(plugin)
                        
                        # 处理列表格式的插件数据（备用）
                        elif isinstance(data, list):
                            for item in data:
                                plugin = self._parse_plugin_data(item)
                                if plugin:
                                    self.plugins.append(plugin)
                        
                        if self.plugins:
                            # 按star数排序
                            self.plugins.sort(key=lambda p: p.stars, reverse=True)
                            
                            # 分配稳定的插件ID（基于排序后的位置）
                            for i, plugin in enumerate(self.plugins, 1):
                                plugin.plugin_id = i
                            
                            loop = asyncio.get_running_loop()
                            self.last_update = loop.time()
                            
                            logger.info(f"成功加载 {len(self.plugins)} 个插件")
                            return True
                        
            except json.JSONDecodeError as e:
                logger.error(f"从 {url} 解析JSON失败: {e}")
                logger.error(f"响应内容: {text_content[:200]}...")
                continue
            except Exception as e:
                logger.error(f"从 {url} 加载失败: {e}")
                logger.error(f"错误类型: {type(e).__name__}")
                continue
        
        logger.error("所有数据源加载失败")
        return False
    
    def _parse_plugin_data(self, item: dict) -> Optional[PluginInfo]:
        """
        解析单个插件数据
        
        Args:
            item: 插件数据字典
            
        Returns:
            PluginInfo: 解析后的插件信息，失败返回None
        """
        try:
            # 适配AstrBot_Plugins_Collection的数据格式
            name = item.get('name', '').strip()
            author = item.get('author', '').strip()
            description = item.get('desc', item.get('description', '')).strip()  # 支持desc和description字段
            repo_url = item.get('repo', item.get('repository', '')).strip()  # 支持repo和repository字段
            
            # 如果没有名称，跳过
            if not name:
                return None
            
            # 如果没有仓库地址，尝试构建GitHub地址
            if not repo_url and author:
                repo_url = f"https://github.com/{author}/{name}"
            
            # 如果仍然没有必要信息，跳过
            if not repo_url:
                return None
            
            return PluginInfo(
                name=name,
                author=author if author else "Unknown",
                description=description,
                repo_url=repo_url,
                stars=item.get('stars', 0),
                language=item.get('language', 'Python'),
                tags=item.get('tags', item.get('topics', []))  # 支持tags和topics字段
            )
        except Exception as e:
            logger.warning(f"解析插件数据失败: {e}")
            return None
    
    async def update_if_needed(self) -> bool:
        """
        按需更新插件数据
        
        Returns:
            bool: 是否需要更新并成功更新
        """
        loop = asyncio.get_running_loop()
        if loop.time() - self.last_update < self.cache_ttl:
            return False
        
        return await self.load_plugins_from_collection()
    
    def search_plugins(self, keyword: str = "") -> List[PluginInfo]:
        """
        搜索插件（模糊匹配）
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            List[PluginInfo]: 匹配的插件列表
        """
        if not keyword:
            return self.plugins
        
        keyword_lower = keyword.lower()
        matched_plugins = []
        
        for plugin in self.plugins:
            # 计算匹配分数
            score = 0
            
            # 检查名称匹配
            if keyword_lower in plugin.name.lower():
                score += 10
                if plugin.name.lower() == keyword_lower:
                    score += 20  # 完全匹配加分
            
            # 检查描述匹配
            if keyword_lower in plugin.description.lower():
                score += 5
            
            # 检查作者匹配
            if keyword_lower in plugin.author.lower():
                score += 8
            
            # 检查标签匹配
            for tag in plugin.tags:
                if keyword_lower in tag.lower():
                    score += 3
                    break
            
            if score > 0:
                matched_plugins.append((score, plugin))
        
        # 按分数和star数排序
        matched_plugins.sort(key=lambda x: (x[0], x[1].stars), reverse=True)
        return [plugin for score, plugin in matched_plugins]
    
    def find_by_author(self, author: str) -> List[PluginInfo]:
        """
        按作者搜索插件
        
        Args:
            author: 作者名
            
        Returns:
            List[PluginInfo]: 该作者的插件列表
        """
        if not author:
            return []
        
        author_lower = author.lower()
        return [
            plugin for plugin in self.plugins
            if author_lower in plugin.author.lower()
        ]
    
    def find_plugin_by_identifier(self, identifier: str) -> Optional[PluginInfo]:
        """
        通过ID、短名称或完整名称查找插件（精确匹配）
        
        Args:
            identifier: 插件标识符（ID、短名称或完整名称）
            
        Returns:
            PluginInfo: 找到的插件，未找到返回None
            
        注意：为避免歧义，只支持精确匹配。如需模糊搜索，请使用 /find_plugins 命令。
        """
        if not identifier:
            return None
        
        identifier = identifier.strip()
        
        # 1. 尝试数字ID匹配（最高优先级）
        if identifier.isdigit():
            plugin_id = int(identifier)
            for plugin in self.plugins:
                if plugin.plugin_id == plugin_id:
                    return plugin
        
        identifier_lower = identifier.lower()
        
        # 2. 尝试短名称精确匹配（不区分大小写）
        for plugin in self.plugins:
            if plugin.short_name.lower() == identifier_lower:
                return plugin
        
        # 3. 尝试完整名称精确匹配（不区分大小写）
        for plugin in self.plugins:
            if plugin.name.lower() == identifier_lower:
                return plugin
        
        # 移除模糊匹配逻辑以避免歧义
        # 用户可以使用 /find_plugins 命令进行模糊搜索
        
        return None

@register("github_star_manager", "山萘", "智能发现和点赞AstrBot插件的GitHub Star管理器", "1.1.0", "https://github.com/shannai37/github_star_plugin")
class GitHubStarManager(Star):
    """
    GitHub Star管理器主类
    集成所有功能，提供用户命令接口
    
    命令功能：
    - show_help(): 显示插件帮助信息（无需权限）
    - find_plugins(): 搜索AstrBot插件（支持分页）
    - find_by_author(): 按作者搜索插件
    - star_plugin(): 给插件点star（支持ID、短名称、完整名称）
    - my_github(): 查看GitHub账户信息
    - test_network(): 测试GitHub API连通性
    - update_plugins(): 手动更新插件数据库
    - debug_config(): 调试配置信息（脱敏处理）
    
    安全特性：
    - 权限检查装饰器（@require_permission）避免代码重复
    - 重构的权限配置解析逻辑（_parse_allowed_users_config）
    - 支持多种权限配置格式（Python列表、JSON字符串、逗号分隔）
    - 精确的插件查找（移除模糊匹配避免歧义）
    - 脱敏的调试信息输出
    - 统一的异常处理和错误报告
    
    核心方法：
    - _parse_allowed_users_config(): 统一的权限配置解析逻辑
    - _check_permission(): 简化的权限检查机制
    - _format_plugin_display(): 统一的插件显示格式化
    - find_plugin_by_identifier(): 精确的插件查找（仅精确匹配）
    """
    
    def __init__(self, context: Context, config: AstrBotConfig):
        """
        初始化插件
        
        Args:
            context: AstrBot上下文对象
            config: 插件配置对象
        """
        super().__init__(context)
        self.config = config
        self.github_client: Optional[GitHubAPIClient] = None
        self.plugin_db = PluginDatabase()
        self.initialized = False
    
    async def initialize(self) -> bool:
        """
        初始化插件组件
        
        Returns:
            bool: 是否初始化成功
        """
        if self.initialized:
            return True
        
        try:
            # 获取配置
            github_token = self.config.get("github_token", "")
            if not github_token:
                logger.error("GitHub token未配置")
                return False
            
            # 初始化GitHub客户端
            self.github_client = GitHubAPIClient(github_token, dict(self.config))
            
            # 验证token
            if not await self.github_client.verify_token():
                logger.error("GitHub token验证失败")
                return False
            
            # 加载插件数据
            if not await self.plugin_db.load_plugins_from_collection():
                logger.error("插件数据加载失败")
                return False
            
            self.initialized = True
            logger.info("GitHub Star Manager初始化成功")
            return True
            
        except Exception as e:
            logger.error(f"初始化失败: {e}")
            return False
    
    def _parse_allowed_users_config(self) -> tuple[list, str]:
        """
        解析权限配置
        
        支持的配置格式：
        1. Python列表: ["123", "456"]
        2. JSON字符串: "[\"123\", \"456\"]"
        3. 逗号分隔: "123,456,789"
        4. 空值: 允许所有用户
        
        Returns:
            tuple: (用户ID列表, 描述信息)
        """
        allowed_users_config = self.config.get("allowed_users", "")
        
        # 处理已经是Python列表的情况（框架已解析）
        if isinstance(allowed_users_config, list):
            user_list = [str(uid) for uid in allowed_users_config if uid is not None]
            if not user_list:  # 空列表允许所有用户
                return [], "允许所有用户访问"
            return user_list, f"用户列表（共{len(user_list)}个用户）"
        
        # 如果配置为空，允许所有用户
        if not allowed_users_config or str(allowed_users_config).strip() == "":
            return [], "允许所有用户访问"
        
        # 处理字符串格式的配置
        if isinstance(allowed_users_config, str):
            try:
                # 支持JSON数组格式："[\"123\", \"456\"]"
                allowed_users = json.loads(allowed_users_config)
                if isinstance(allowed_users, list):
                    user_list = [str(uid) for uid in allowed_users if uid is not None]
                    if not user_list:  # 空列表允许所有用户
                        return [], "允许所有用户访问"
                    return user_list, f"JSON用户列表（共{len(user_list)}个用户）"
                else:
                    return [], "不支持的JSON格式（非array）"
            except json.JSONDecodeError:
                # 支持逗号分隔格式："123,456,789"
                user_list = [uid.strip() for uid in allowed_users_config.split(',') if uid.strip()]
                if not user_list:  # 空列表允许所有用户
                    return [], "允许所有用户访问"
                return user_list, f"逗号分隔的用户列表（共{len(user_list)}个用户）"
        
        # 其他不支持的类型，记录警告并允许所有用户访问
        logger.warning(f"不支持的allowed_users配置类型: {type(allowed_users_config).__name__}, 将允许所有用户访问")
        return [], f"不支持的配置类型: {type(allowed_users_config).__name__}"
    
    def _check_permission(self, user_id: str) -> bool:
        """
        检查用户权限（简化版）
        
        Args:
            user_id: 用户ID
            
        Returns:
            bool: 是否有权限
            
        支持的配置格式：
        - JSON数组: ["123", "456"]
        - 逗号分隔: "123,456,789" 
        - 空值: 允许所有用户
        """
        try:
            user_list, _ = self._parse_allowed_users_config()
            
            # 如果没有配置或空列表，允许所有用户
            if not user_list:
                return True
            
            # 检查用户ID是否在允许列表中
            return str(user_id) in user_list
            
        except Exception as e:
            logger.error(f"权限检查异常: {e}")
            return False  # 故障安全：异常时拒绝访问
    
    async def _format_plugin_display(self, plugins: List[PluginInfo], title: str, page: int = 1, page_size: int = 8, update_stars: bool = False) -> str:
        """
        统一的插件显示格式化方法
        
        Args:
            plugins: 插件列表
            title: 显示标题
            page: 页码（默认为1）
            page_size: 每页显示的插件数量（默认为8）
            update_stars: 是否实时更新star数（最多更新10个，默认False）
            
        Returns:
            str: 格式化后的插件列表显示文本，包含分页信息和使用说明
        """
        if not plugins:
            return "未找到匹配的插件"
        
        # 可选地更新star数（仅对前几个插件，避免太慢）
        if update_stars and self.github_client:
            update_count = min(len(plugins), 10)  # 最多更新前10个
            for plugin in plugins[:update_count]:
                try:
                    await self.github_client.update_plugin_stars(plugin)
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.debug(f"更新插件 {plugin.short_name} 的star数失败: {e}")
                except Exception as e:
                    logger.warning(f"更新插件 {plugin.short_name} 时发生意外错误: {e}")
        
        # 分页逻辑
        total_pages = (len(plugins) + page_size - 1) // page_size
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages
        
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_plugins = plugins[start_idx:end_idx]
        
        # 构建显示文本
        result = f"🔍 {title} - 找到 {len(plugins)} 个插件 (第{page}/{total_pages}页):\n\n"
        
        for plugin in page_plugins:
            result += f"[{plugin.plugin_id}] 📦 {plugin.short_name}\n"
            result += f"    👤 {plugin.author} | ⭐ {plugin.stars}\n"
            result += f"    📝 {plugin.description[:60]}{'...' if len(plugin.description) > 60 else ''}\n"
            result += f"    🔗 {plugin.repo_url}\n\n"
        
        # 分页导航
        if total_pages > 1:
            nav_info = f"📄 第{page}/{total_pages}页"
            result += nav_info + "\n\n"
        
        result += "💡 使用 /star_plugin <ID或名称> 来给插件点star\n"
        result += "💡 示例: /star_plugin 1 或 /star_plugin context_enhancer"
        
        return result
    
    @filter.command("github_help")
    async def show_help(self, event: AstrMessageEvent):
        """显示插件帮助信息"""
        help_text = """🌟 GitHub Star Manager 帮助

📋 可用命令:
• /find_plugins [关键词] [页码] - 搜索AstrBot插件（支持分页）
• /find_by_author <作者> - 按作者搜索插件
• /star_plugin <ID或名称> - 给插件点star
• /list_installed [页码] - 显示已安装插件及star状态
• /starall - 批量star所有已安装的GitHub插件
• /my_github - 查看GitHub账户信息
• /test_network - 测试GitHub API连通性
• /update_plugins - 手动更新插件数据库
• /debug_config - 调试配置信息

💡 使用示例:
• /find_plugins 天气 - 搜索天气相关插件
• /find_plugins 天气 2 - 搜索结果第2页
• /find_by_author anka-afk - 查找该作者的所有AstrBot插件
• /star_plugin 1 - 给ID为1的插件点star
• /star_plugin context_enhancer - 给短名称匹配的插件点star
• /list_installed - 查看已安装插件列表
• /list_installed 2 - 查看已安装插件第2页
• /starall - 批量star所有已安装的GitHub插件

🔍 插件标识符说明:
• 数字ID: [1] [2] [3] (显示在搜索结果中)
• 短名称: context_enhancer (自动生成的简短名称)
• 完整名称: astrbot_plugin_context_enhancer

⚙️ 配置说明:
需要在插件配置中设置你的GitHub Personal Access Token"""
        
        yield event.plain_result(help_text)
    
    @filter.command("find_plugins")
    @require_permission
    async def find_plugins(self, event: AstrMessageEvent, keyword: str = "", page: int = 1):
        """
        搜索AstrBot插件（支持分页）
        
        Args:
            keyword: 搜索关键词
            page: 页码（默认第1页）
        """
        try:
            
            await self.initialize()
            if not self.initialized:
                yield event.plain_result("❌ 插件未正确初始化")
                return
            
            yield event.plain_result("🔍 搜索插件中...")
            
            # 更新插件数据（如果需要）
            await self.plugin_db.update_if_needed()
            
            # 搜索插件
            plugins = self.plugin_db.search_plugins(keyword)
            
            if not plugins:
                yield event.plain_result(f"未找到匹配的插件: {keyword}")
                return
            
            # 使用统一格式化方法，并更新star数
            search_info = f"关键词: {keyword}" if keyword else "全部插件"
            result = await self._format_plugin_display(
                plugins=plugins, 
                title=search_info, 
                page=page, 
                page_size=8,
                update_stars=True  # 显示时更新star数
            )
            
            yield event.plain_result(result)
            
        except Exception as e:
            logger.error(f"搜索插件失败: {e}")
            yield event.plain_result(f"❌ 搜索失败: {str(e)}")
    
    @filter.command("find_by_author")
    @require_permission
    async def find_by_author(self, event: AstrMessageEvent, author: str):
        """
        按作者搜索AstrBot插件
        
        Args:
            author: 作者名
        """
        try:
            
            await self.initialize()
            if not self.initialized:
                yield event.plain_result("❌ 插件未正确初始化")
                return
            
            if not author.strip():
                yield event.plain_result("请输入作者名称进行搜索")
                return
            
            yield event.plain_result("🔍 按作者搜索中...")
            
            # 更新插件数据（如果需要）
            await self.plugin_db.update_if_needed()
            
            # 搜索插件
            plugins = self.plugin_db.find_by_author(author)
            
            if not plugins:
                yield event.plain_result(f"未找到作者 '{author}' 的插件")
                return
            
            # 按star数排序
            plugins.sort(key=lambda p: p.stars, reverse=True)
            
            # 使用统一格式化方法，并更新star数
            result = await self._format_plugin_display(
                plugins=plugins,
                title=f"作者 '{author}' 的插件",
                page=1,
                page_size=8,
                update_stars=True  # 显示时更新star数
            )
            
            yield event.plain_result(result)
            
        except Exception as e:
            logger.error(f"按作者搜索失败: {e}")
            yield event.plain_result(f"❌ 搜索失败: {str(e)}")
    
    @filter.command("star_plugin")
    @require_permission
    async def star_plugin(self, event: AstrMessageEvent, plugin_identifier: str):
        """
        给插件点star（支持ID、短名称或完整名称）
        
        Args:
            plugin_identifier: 插件标识符（ID、短名称或完整名称）
        """
        try:
            
            await self.initialize()
            if not self.initialized:
                yield event.plain_result("❌ 插件未正确初始化")
                return
            
            if not plugin_identifier.strip():
                yield event.plain_result("请输入插件ID、短名称或完整名称")
                return
            
            # 查找插件
            plugin = self.plugin_db.find_plugin_by_identifier(plugin_identifier)
            if not plugin:
                yield event.plain_result(f"未找到插件: {plugin_identifier}\n💡 使用 /find_plugins 搜索插件")
                return
            
            # 实时更新star数
            plugin = await self.github_client.update_plugin_stars(plugin)
            
            owner, repo = self.github_client._parse_repo_url(plugin.repo_url)
            
            if not owner or not repo:
                yield event.plain_result("❌ 无法解析仓库地址")
                return
            
            yield event.plain_result(f"⭐ 正在给 [{plugin.plugin_id}] {plugin.short_name} 点star...")
            
            # 检查是否已点star
            try:
                already_starred = await self.github_client.check_star_status(owner, repo)
                if already_starred:
                    yield event.plain_result(f"✅ 你已经给 {plugin.short_name} 点过star了\n当前⭐数量: {plugin.stars}")
                    return
            except RepositoryNotFoundError:
                yield event.plain_result(f"❌ 仓库不存在或无权访问: {plugin.repo_url}")
                return
            except NotStarredError:
                # 仓库存在但未star，继续点star流程
                pass
            except NetworkError:
                yield event.plain_result("⚠️ 无法检查star状态（网络错误），继续尝试点star...")
            except Exception as e:
                yield event.plain_result(f"⚠️ 检查star状态失败: {str(e)}，继续尝试点star...")
            
            # 点star
            success = await self.github_client.star_repository(owner, repo)
            if success:
                # 重新获取star数
                plugin = await self.github_client.update_plugin_stars(plugin)
                yield event.plain_result(f"🌟 成功给 {plugin.short_name} 点star！\n当前⭐数量: {plugin.stars}")
            else:
                yield event.plain_result(f"❌ 点star失败")
            
        except Exception as e:
            logger.error(f"点star失败: {e}")
            yield event.plain_result(f"❌ 操作失败: {str(e)}")
    
    @filter.command("my_github")
    @require_permission
    async def my_github(self, event: AstrMessageEvent):
        """查看GitHub账户信息"""
        try:
            
            await self.initialize()
            if not self.initialized:
                yield event.plain_result("❌ 插件未正确初始化")
                return
            
            # 获取用户信息
            user_info = await self.github_client._make_request("GET", f"{self.github_client.api_base_url}/user")
            
            result = f"""👤 GitHub账户信息:
用户名: {user_info.get('login', 'N/A')}
昵称: {user_info.get('name', 'N/A')}
公开仓库: {user_info.get('public_repos', 0)}
关注者: {user_info.get('followers', 0)}
关注中: {user_info.get('following', 0)}
个人主页: {user_info.get('html_url', 'N/A')}"""
            
            yield event.plain_result(result)
            
        except Exception as e:
            logger.error(f"获取GitHub信息失败: {e}")
            yield event.plain_result(f"❌ 获取失败: {str(e)}")
    
    @filter.command("update_plugins")
    @require_permission
    async def update_plugins(self, event: AstrMessageEvent):
        """手动更新插件数据库"""
        try:
            
            yield event.plain_result("🔄 正在更新插件数据库...")
            
            success = await self.plugin_db.load_plugins_from_collection()
            if success:
                yield event.plain_result(f"✅ 插件数据库更新成功，共 {len(self.plugin_db.plugins)} 个插件")
            else:
                yield event.plain_result("❌ 插件数据库更新失败，请检查日志")
            
        except Exception as e:
            logger.error(f"更新插件数据库失败: {e}")
            yield event.plain_result(f"❌ 更新失败: {str(e)}")
    
    @filter.command("debug_config")
    @require_permission
    async def debug_config(self, event: AstrMessageEvent):
        """调试配置信息"""
        user_id = event.get_sender_id()
        
        # 使用重构后的权限配置解析方法
        user_list, allowed_info = self._parse_allowed_users_config()
        
        # 获取插件数据库统计
        plugin_count = len(self.plugin_db.plugins) if self.plugin_db.plugins else 0
        loop = asyncio.get_running_loop()
        last_update = "从未更新" if self.plugin_db.last_update == 0 else f"{int(loop.time() - self.plugin_db.last_update)}秒前"
        
        debug_info = f"""🔧 调试信息:
👤 当前用户ID: {user_id} (类型: {type(user_id).__name__})
🛡️ 权限配置: {allowed_info}
🛡️ 权限检查结果: {self._check_permission(user_id)}

📊 插件数据库状态:
🔢 插件总数: {plugin_count}
🕒 上次更新: {last_update}
🔗 初始化状态: {'已初始化' if self.initialized else '未初始化'}

📋 配置概览:
GitHub Token: {'已配置' if self.config.get('github_token') else '未配置'}
请求超时: {self.config.get('api_settings', {}).get('request_timeout', 20)}秒"""
        
        yield event.plain_result(debug_info)
    
    def _match_installed_with_github_plugins(self, installed_plugins: list) -> list:
        """
        将已安装插件与GitHub插件库进行匹配
        
        Args:
            installed_plugins: 已安装插件的StarMetadata列表
            
        Returns:
            list: 匹配成功的插件信息列表，包含GitHub插件库的ID
        """
        matched_plugins = []
        
        for installed in installed_plugins:
            # 获取已安装插件信息
            installed_name = getattr(installed, 'name', '')
            installed_repo = getattr(installed, 'repo', '')
            installed_author = getattr(installed, 'author', '')
            
            if not installed_name:
                continue
                
            # 尝试在GitHub插件库中找到匹配的插件
            matching_github_plugin = None
            
            # 方法1: 通过repo地址精确匹配
            if installed_repo:
                for github_plugin in self.plugin_db.plugins:
                    if github_plugin.repo_url and installed_repo:
                        # 标准化仓库地址进行比较
                        github_repo_normalized = github_plugin.repo_url.lower().rstrip('/')
                        installed_repo_normalized = installed_repo.lower().rstrip('/')
                        
                        # 移除.git后缀
                        if github_repo_normalized.endswith('.git'):
                            github_repo_normalized = github_repo_normalized[:-4]
                        if installed_repo_normalized.endswith('.git'):
                            installed_repo_normalized = installed_repo_normalized[:-4]
                        
                        if github_repo_normalized == installed_repo_normalized:
                            matching_github_plugin = github_plugin
                            break
            
            # 方法2: 如果repo地址匹配失败，尝试通过插件名匹配
            if not matching_github_plugin:
                for github_plugin in self.plugin_db.plugins:
                    if github_plugin.name.lower() == installed_name.lower():
                        matching_github_plugin = github_plugin
                        break
            
            # 方法3: 尝试通过作者+插件名组合匹配
            if not matching_github_plugin and installed_author:
                for github_plugin in self.plugin_db.plugins:
                    if (github_plugin.author.lower() == installed_author.lower() and 
                        github_plugin.name.lower() == installed_name.lower()):
                        matching_github_plugin = github_plugin
                        break
            
            # 构建匹配结果
            plugin_info = {
                'installed_plugin': installed,
                'name': installed_name,
                'author': installed_author,
                'version': getattr(installed, 'version', ''),
                'repo_url': installed_repo,
                'github_plugin': matching_github_plugin,
                'plugin_id': matching_github_plugin.plugin_id if matching_github_plugin else None,
                'is_matched': matching_github_plugin is not None
            }
            
            matched_plugins.append(plugin_info)
        
        return matched_plugins
    
    @filter.command("list_installed")
    @require_permission
    async def list_installed(self, event: AstrMessageEvent, page: int = 1):
        """
        显示已安装插件及其star状态（支持分页）
        
        Args:
            page: 页码（默认第1页）
        """
        try:
            await self.initialize()
            if not self.initialized:
                yield event.plain_result("❌ 插件未正确初始化")
                return
            
            yield event.plain_result("🔍 正在获取已安装插件列表...")
            
            # 获取已安装插件
            all_stars = self.context.get_all_stars()
            if not all_stars:
                yield event.plain_result("❌ 未获取到任何已安装插件")
                return
            
            # 更新GitHub插件数据库（如果需要）
            await self.plugin_db.update_if_needed()
            
            # 匹配已安装插件与GitHub插件库
            matched_plugins = self._match_installed_with_github_plugins(all_stars)
            
            if not matched_plugins:
                yield event.plain_result("❌ 插件匹配失败")
                return
            
            # 分页设置
            page_size = 8
            total_pages = (len(matched_plugins) + page_size - 1) // page_size
            if page < 1:
                page = 1
            elif page > total_pages:
                page = total_pages
            
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            page_plugins = matched_plugins[start_idx:end_idx]
            
            yield event.plain_result("⏳ 检查star状态中...")
            
            # 构建显示结果
            result = f"🔍 已安装插件列表 - 共{len(matched_plugins)}个插件 (第{page}/{total_pages}页):\n\n"
            
            # 分类统计
            github_matched = sum(1 for p in matched_plugins if p['is_matched'])
            local_only = len(matched_plugins) - github_matched
            
            result += f"📊 分类统计: GitHub插件 {github_matched}个 | 本地插件 {local_only}个\n\n"
            
            for plugin_info in page_plugins:
                if plugin_info['is_matched']:
                    # GitHub插件，显示ID和star状态
                    plugin_id = plugin_info['plugin_id']
                    
                    # 检查star状态
                    star_status = "⚠️"  # 默认状态
                    try:
                        owner, repo = self.github_client._parse_repo_url(plugin_info['repo_url'])
                        if owner and repo:
                            is_starred = await self.github_client.check_star_status(owner, repo)
                            star_status = "⭐" if is_starred else "☆"
                        else:
                            logger.debug(f"无法解析仓库地址: {plugin_info['repo_url']}")
                            star_status = "⚠️"
                    except NotStarredError:
                        # 仓库存在但未被star
                        star_status = "☆"
                    except RepositoryNotFoundError:
                        # 仓库不存在
                        logger.debug(f"仓库不存在: {plugin_info['repo_url']}")
                        star_status = "⚠️"
                    except (AuthenticationError, PermissionError) as e:
                        # Token认证或权限问题
                        logger.debug(f"GitHub认证/权限错误: {e}")
                        star_status = "⚠️"
                    except (RateLimitError, NetworkError) as e:
                        # 网络问题或API限流
                        logger.debug(f"网络错误: {e}")
                        star_status = "⚠️"
                    except Exception as e:
                        logger.debug(f"检查{plugin_info['name']}的star状态失败: {e}")
                        star_status = "⚠️"
                    
                    result += f"[{plugin_id}] 📦 {plugin_info['name']} {star_status}\n"
                    result += f"    👤 {plugin_info['author']} | 🏷️ {plugin_info['version']}\n"
                    result += f"    🔗 {plugin_info['repo_url']}\n\n"
                else:
                    # 本地插件，不显示ID
                    result += f"🔧 {plugin_info['name']} (本地插件)\n"
                    result += f"    👤 {plugin_info['author']} | 🏷️ {plugin_info['version']}\n"
                    if plugin_info['repo_url']:
                        result += f"    🔗 {plugin_info['repo_url']} (未在GitHub插件库中找到)\n"
                    result += "\n"
            
            # 分页导航
            if total_pages > 1:
                result += f"📄 第{page}/{total_pages}页"
                if page < total_pages:
                    result += f" | 下一页: /list_installed {page + 1}"
                if page > 1:
                    result += f" | 上一页: /list_installed {page - 1}"
                result += "\n\n"
            
            result += "💡 使用说明:\n"
            result += "• /star_plugin <ID> - 给指定插件点star\n"
            result += "• /starall - 批量star所有GitHub插件\n"
            result += "• ⭐ = 已star | ☆ = 未star | ⚠️ = 无法检查"
            
            yield event.plain_result(result)
            
        except Exception as e:
            logger.error(f"获取已安装插件列表失败: {e}")
            yield event.plain_result(f"❌ 操作失败: {str(e)}")
    
    @filter.command("starall")
    @require_permission
    async def star_all_installed(self, event: AstrMessageEvent):
        """
        批量star所有已安装的GitHub插件
        """
        try:
            await self.initialize()
            if not self.initialized:
                yield event.plain_result("❌ 插件未正确初始化")
                return
            
            yield event.plain_result("🌟 开始批量star操作...")
            
            # 获取已安装插件
            all_stars = self.context.get_all_stars()
            if not all_stars:
                yield event.plain_result("❌ 未获取到任何已安装插件")
                return
            
            # 更新GitHub插件数据库
            await self.plugin_db.update_if_needed()
            
            # 匹配已安装插件与GitHub插件库
            matched_plugins = self._match_installed_with_github_plugins(all_stars)
            
            # 过滤出GitHub插件（有ID的）
            github_plugins = [p for p in matched_plugins if p['is_matched']]
            local_plugins = [p for p in matched_plugins if not p['is_matched']]
            
            # 添加github_star_manager插件本身（确保包含在批量star中）
            github_star_manager_plugin = None
            for plugin in self.plugin_db.plugins:
                if plugin.name.lower() == "github_star_manager" or "github_star_manager" in plugin.name.lower():
                    github_star_manager_plugin = plugin
                    break
            
            # 如果找到了github_star_manager插件且不在已安装列表中，添加它
            if github_star_manager_plugin:
                # 检查是否已经在已安装列表中
                already_included = any(p.get('plugin_id') == github_star_manager_plugin.plugin_id for p in github_plugins)
                if not already_included:
                    github_plugins.append({
                        'name': github_star_manager_plugin.name,
                        'author': github_star_manager_plugin.author,
                        'repo_url': github_star_manager_plugin.repo_url,
                        'plugin_id': github_star_manager_plugin.plugin_id,
                        'is_matched': True,
                        'github_plugin': github_star_manager_plugin
                    })
            
            if not github_plugins:
                yield event.plain_result("❌ 没有找到可以star的GitHub插件")
                return
            
            # 显示统计信息
            status_msg = f"扫描已安装插件: {len(matched_plugins)}个\n"
            status_msg += f"匹配到GitHub库: {len(github_plugins)}个\n"
            status_msg += f"跳过本地插件: {len(local_plugins)}个\n\n"
            status_msg += "检查star状态..."
            
            yield event.plain_result(status_msg)
            
            # 检查每个插件的star状态
            to_star = []
            already_starred = []
            check_failed = []
            
            for i, plugin_info in enumerate(github_plugins, 1):
                try:
                    owner, repo = self.github_client._parse_repo_url(plugin_info['repo_url'])
                    if owner and repo:
                        # 检查是否已star
                        is_starred = await self.github_client.check_star_status(owner, repo)
                        if is_starred:
                            already_starred.append(plugin_info)
                        else:
                            to_star.append(plugin_info)
                    else:
                        logger.debug(f"无法解析仓库地址: {plugin_info['repo_url']}")
                        check_failed.append(plugin_info)
                        
                except NotStarredError:
                    # 仓库存在但未star
                    to_star.append(plugin_info)
                except RepositoryNotFoundError:
                    logger.debug(f"仓库不存在: {plugin_info['repo_url']}")
                    check_failed.append(plugin_info)
                except Exception as e:
                    logger.debug(f"检查{plugin_info['name']}的star状态失败: {e}")
                    check_failed.append(plugin_info)
            
            # 显示检查结果
            check_result = f"📊 Star状态检查完成:\n"
            check_result += f"需要star: {len(to_star)}个\n"
            check_result += f"已经star: {len(already_starred)}个\n"
            check_result += f"检查失败: {len(check_failed)}个\n\n"
            
            if not to_star:
                check_result += "🎉 所有GitHub插件都已经star了！"
                yield event.plain_result(check_result)
                return
            
            check_result += "🚀 正在为您的插件点赞中，请耐心等待... (￣▽￣)~*"
            yield event.plain_result(check_result)
            
            # 批量star操作（静默执行）
            success_count = 0
            failed_count = 0
            success_plugins = []
            failed_plugins = []
            
            for i, plugin_info in enumerate(to_star, 1):
                try:
                    plugin_name = plugin_info['name']
                    plugin_id = plugin_info.get('plugin_id', 'N/A')
                    
                    owner, repo = self.github_client._parse_repo_url(plugin_info['repo_url'])
                    if owner and repo:
                        success = await self.github_client.star_repository(owner, repo)
                        if success:
                            success_count += 1
                            success_plugins.append(f"✅ {plugin_name}")
                        else:
                            failed_count += 1
                            failed_plugins.append(f"❌ {plugin_name} - star失败")
                    else:
                        failed_count += 1
                        failed_plugins.append(f"❌ {plugin_name} - 无法解析仓库地址")
                        
                except Exception as e:
                    failed_count += 1
                    logger.error(f"star插件 {plugin_info['name']} 失败: {e}")
                    failed_plugins.append(f"❌ {plugin_info['name']} - 异常: {str(e)}")
                
                # 添加小延迟避免API限流
                if i < len(to_star):  # 不是最后一个
                    await asyncio.sleep(0.5)
            
            # 最终统计报告
            final_report = f"\n📊 批量star操作完成:\n\n"
            
            # 显示成功列表
            if success_plugins:
                final_report += f"🌟 成功star ({success_count}个):\n"
                for plugin in success_plugins:
                    final_report += f"  {plugin}\n"
                final_report += "\n"
            
            # 显示失败列表  
            if failed_plugins:
                final_report += f"❌ 失败列表 ({failed_count}个):\n"
                for plugin in failed_plugins:
                    final_report += f"  {plugin}\n"
                final_report += "\n"
            
            # 统计汇总
            final_report += f"📈 汇总统计:\n"
            final_report += f"✅ 成功: {success_count}个\n"
            final_report += f"❌ 失败: {failed_count}个\n"
            final_report += f"⏭️ 跳过: {len(already_starred)}个 (已star)\n"
            final_report += f"⚠️ 忽略: {len(check_failed)}个 (检查失败)\n"
            final_report += f"🔧 本地插件: {len(local_plugins)}个 (无GitHub仓库)\n\n"
            
            if success_count > 0:
                final_report += f"🎉 感谢您为{success_count}个AstrBot插件点star！"
            
            yield event.plain_result(final_report)
            
        except Exception as e:
            logger.error(f"批量star操作失败: {e}")
            yield event.plain_result(f"❌ 批量star操作失败: {str(e)}")
    
    @filter.command("test_network")
    @require_permission
    async def test_network(self, event: AstrMessageEvent):
        """测试GitHub API连通性"""
        try:
            
            await self.initialize()
            if not self.initialized:
                yield event.plain_result("❌ 插件未正确初始化")
                return
            
            yield event.plain_result("🔍 测试GitHub API连通性...")
            
            # 测试所有端点
            results = await self.github_client.test_connectivity()
            
            result_text = "📊 网络连通性测试结果:\n\n"
            
            working_endpoints = []
            for endpoint, status in results.items():
                if status['success']:
                    icon = "✅"
                    latency_info = f" ({status['latency']}ms)"
                    working_endpoints.append((endpoint, status['latency']))
                else:
                    icon = "❌" 
                    latency_info = f" - {status.get('error', '连接失败')}"
                
                # 简化端点显示
                display_name = endpoint.replace("https://", "").replace("/api", "")
                if len(display_name) > 30:
                    display_name = display_name[:27] + "..."
                
                result_text += f"{icon} {display_name}{latency_info}\n"
            
            # 显示连通结果
            if working_endpoints:
                best_endpoint, best_latency = min(working_endpoints, key=lambda x: x[1])
                best_name = best_endpoint.replace("https://", "").replace("/api", "")
                if len(best_name) > 30:
                    best_name = best_name[:27] + "..."
                result_text += f"\n🚀 GitHub API连通正常: {best_latency}ms"
            else:
                result_text += "\n⚠️ 所有端点都无法访问，请检查:\n"
                result_text += "  • 网络连接\n"
                result_text += "  • GitHub Token是否有效\n"
                result_text += "  • 防火墙设置"
            
            yield event.plain_result(result_text)
            
        except Exception as e:
            logger.error(f"网络测试失败: {e}")
            yield event.plain_result(f"❌ 网络测试失败: {str(e)}")
    
    async def terminate(self):
        """插件被卸载时调用"""
        logger.info("GitHub Star Manager插件已卸载")
