# -*- coding: utf-8 -*-

import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

import urllib3

# 配置日志
urllib3.disable_warnings()
logging.captureWarnings(True)
logger = logging.getLogger(__name__)


class FileUtil:
    """文件操作工具类，提供文件和目录的常用操作"""

    @staticmethod
    def _validate_path(path: str) -> bool:
        """验证路径是否存在且可访问"""
        if not path or not os.path.exists(path):
            logger.error(f"路径不存在: {path}")
            return False
        return True

    @staticmethod
    def _match_pattern(filename: str, pattern: str) -> bool:
        """简单的文件名模式匹配"""
        if '*' not in pattern and '?' not in pattern:
            return filename == pattern
        import fnmatch
        return fnmatch.fnmatch(filename, pattern)

    @staticmethod
    def _process_file(
            root: str,
            filename: str,
            min_size: int,
            include_size: bool,
            result: List[Any]
    ) -> None:
        """处理单个文件并添加到结果列表"""
        file_path = os.path.join(root, filename)
        try:
            size = os.path.getsize(file_path)
            if size >= min_size:
                if include_size:
                    result.append({
                        'name': filename,
                        'path': file_path,
                        'size': size
                    })
                else:
                    result.append(filename)
        except OSError as e:
            logger.warning(f"无法访问文件: {file_path}, 错误: {e}")

    @staticmethod
    def list_files(
            path: str,
            recursive: bool = True,
            include_size: bool = False,
            min_size: int = 0,
            pattern: Optional[str] = None
    ) -> Union[List[str], List[Dict[str, Any]]]:
        """
        遍历目录下的所有文件，支持更多过滤选项

        Args:
            path: 要遍历的目录路径
            recursive: 是否递归遍历子目录
            include_size: 是否包含文件大小信息
            min_size: 最小文件大小（字节），默认为0
            pattern: 文件名匹配模式，支持简单的通配符（例如 *.txt）

        Returns:
            如果include_size为False，返回文件名列表；否则返回包含文件名和大小的字典列表
        """
        if not FileUtil._validate_path(path):
            return []

        logger.info(f"开始遍历目录: {path}, 递归: {recursive}, 最小文件大小: {min_size}字节")
        result = []

        if recursive:
            for root, _, files in os.walk(path):
                for filename in files:
                    if pattern and not FileUtil._match_pattern(filename, pattern):
                        continue
                    FileUtil._process_file(root, filename, min_size, include_size, result)
        else:
            for filename in os.listdir(path):
                file_path = os.path.join(path, filename)
                if os.path.isfile(file_path):
                    if pattern and not FileUtil._match_pattern(filename, pattern):
                        continue
                    FileUtil._process_file(path, filename, min_size, include_size, result)

        logger.info(f"目录遍历完成: {path}, 找到文件数: {len(result)}")
        return result

    @staticmethod
    def get_file_dict(
            path: str,
            key_by_name: bool = True,
            include_size: bool = True,
            recursive: bool = True,
            min_size: int = 0
    ) -> Dict[str, Any]:
        """
        获取目录下所有文件的字典映射

        Args:
            path: 要遍历的目录路径
            key_by_name: 是否使用文件名作为键（否则使用完整路径）
            include_size: 是否在值中包含文件大小
            recursive: 是否递归遍历子目录
            min_size: 最小文件大小（字节）

        Returns:
            文件字典，键为文件名或完整路径，值为文件路径或包含路径和大小的字典
        """
        if not FileUtil._validate_path(path):
            return {}

        logger.info(f"开始构建文件字典: {path}")
        file_dict = {}

        for root, _, files in os.walk(path):
            for filename in files:
                file_path = os.path.join(root, filename)
                try:
                    size = os.path.getsize(file_path)
                    if size >= min_size:
                        key = filename if key_by_name else file_path
                        if include_size:
                            file_dict[key] = {
                                'path': file_path,
                                'size': size
                            }
                        else:
                            file_dict[key] = file_path
                except OSError as e:
                    logger.warning(f"无法访问文件: {file_path}, 错误: {e}")

            # 如果不递归，只处理当前目录
            if not recursive:
                break

        logger.info(f"文件字典构建完成: {path}, 文件数: {len(file_dict)}")
        return file_dict

    @staticmethod
    def read_file(
            file_path: str,
            mode: str = 'r',
            encoding: str = 'utf-8',
            max_size: Optional[int] = None
    ) -> Optional[Union[str, bytes]]:
        """
        读取文件内容，支持大小限制和异常处理

        Args:
            file_path: 文件路径
            mode: 打开模式
            encoding: 编码格式（文本模式下）
            max_size: 最大读取字节数，超出将返回None

        Returns:
            文件内容，失败返回None
        """
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            logger.error(f"文件不存在: {file_path}")
            return None

        file_size = os.path.getsize(file_path)
        if max_size and file_size > max_size:
            logger.error(f"文件大小超出限制: {file_path}, 大小: {file_size}字节, 限制: {max_size}字节")
            return None

        try:
            if 'b' in mode:
                with open(file_path, mode) as f:
                    return f.read(max_size) if max_size else f.read()
            else:
                with open(file_path, mode, encoding=encoding) as f:
                    return f.read(max_size) if max_size else f.read()
        except UnicodeDecodeError:
            logger.error(f"文件编码错误: {file_path}, 请尝试使用二进制模式读取")
        except PermissionError:
            logger.error(f"没有权限读取文件: {file_path}")
        except Exception as e:
            logger.error(f"读取文件失败: {file_path}, 错误: {e}")
        return None

    @staticmethod
    def write_file(
            file_path: str,
            content: Union[str, bytes],
            mode: str = 'w',
            encoding: str = 'utf-8',
            atomic: bool = False
    ) -> bool:
        """
        写入文件内容，支持原子写入

        Args:
            file_path: 文件路径
            content: 要写入的内容
            mode: 写入模式
            encoding: 编码格式（文本模式下）
            atomic: 是否使用原子写入（先写入临时文件，成功后再重命名）

        Returns:
            成功返回True，失败返回False
        """
        try:
            dir_path = os.path.dirname(file_path)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)

            if atomic:
                temp_path = f"{file_path}.tmp"
                try:
                    if 'b' in mode:
                        with open(temp_path, mode) as f:
                            f.write(content)
                    else:
                        with open(temp_path, mode, encoding=encoding) as f:
                            f.write(content)
                    os.replace(temp_path, file_path)
                finally:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except:
                            pass
            else:
                if 'b' in mode:
                    with open(file_path, mode) as f:
                        f.write(content)
                else:
                    with open(file_path, mode, encoding=encoding) as f:
                        f.write(content)

            # logger.info(f"文件写入成功: {file_path}")
            return True
        except PermissionError:
            logger.error(f"没有权限写入文件: {file_path}")
        except Exception as e:
            logger.error(f"写入文件失败: {file_path}, 错误: {e}")
        return False

    @staticmethod
    def get_file_info(file_path: str) -> Optional[Dict[str, Any]]:
        """
        获取文件的详细信息

        Args:
            file_path: 文件路径

        Returns:
            包含文件信息的字典，失败返回None
        """
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            logger.error(f"文件不存在: {file_path}")
            return None

        try:
            stat_info = os.stat(file_path)
            return {
                'path': file_path,
                'name': os.path.basename(file_path),
                'size': stat_info.st_size,
                'created_time': stat_info.st_ctime,
                'modified_time': stat_info.st_mtime,
                'access_time': stat_info.st_atime,
                'is_readonly': not os.access(file_path, os.W_OK)
            }
        except Exception as e:
            logger.error(f"获取文件信息失败: {file_path}, 错误: {e}")
            return None


# 保持向后兼容性的函数

def read_file(
        file_path: str,
        mode: str = 'r',
        encoding: str = 'utf-8'
) -> Optional[Union[str, bytes]]:
    """向后兼容的函数：读取文件内容"""
    return FileUtil.read_file(file_path, mode=mode, encoding=encoding)


def write_file(
        file_path: str,
        content: Union[str, bytes],
        mode: str = 'w',
        encoding: str = 'utf-8'
) -> bool:
    """向后兼容的函数：写入文件内容"""
    return FileUtil.write_file(file_path, content, mode=mode, encoding=encoding)


def find_project_root(
        current_file: str,
        markers=("main.py", ".env", "requirements.txt")
) -> Path:
    current_path = Path(current_file).parent
    for parent in current_path.parents:
        for marker in markers:
            if (parent / marker).exists():
                return parent
    return current_path
# PROJECT_ROOT = find_project_root(__file__)
# sys.path.append(str(PROJECT_ROOT))
