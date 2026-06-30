"""
API 请求模式模块
定义了 Web API 层的请求体数据结构，用于 FastAPI 的请求参数校验。
每个模式对应一个或一组 API 端点的请求体。
API 请求模式与内部状态模型的映射关系：
  CreateBookRequest    → 初始化 NovelState + 创建 workspace 目录
  SelectBookRequest    → 加载已有 NovelState
  AddChapterRequest    → 调用 chapter_service.add_chapter()
  UpdateChapterRequest → 调用 chapter_service.update_chapter()
  UpdateFieldRequest   → 调用 NovelMemory.save_field_content() 或触发生成流
"""

from pydantic import BaseModel


class CreateBookRequest(BaseModel):
    """创建书籍请求"""

    title: str


class SelectBookRequest(BaseModel):
    """选择书籍请求"""

    name: str


class AddChapterRequest(BaseModel):
    """添加章节请求"""

    title: str
    content: str = ""
    content_summary: str = ""


class UpdateChapterRequest(BaseModel):
    """更新章节请求"""

    title: str
    content: str


class UpdateFieldRequest(BaseModel):
    """
    更新字段请求
    用于多种场景：
    - 直接编辑字段内容（field + value）
    - AI 生成章节标题（field + value 作为额外要求）
    """

    field: str
    value: str
    user_request: str = ""
    field_values: dict[str, str] = {}


class ResumeRequest(BaseModel):
    """
    恢复 interrupt 暂停的 Agent 请求
    前端/桌面端/iOS 端在收到 interrupt 事件后，
    调用 /api/chat/resume 恢复 Agent 执行。
    Attributes:
        value: 用户的确认选择，会作为 interrupt() 的返回值
               通常为 True/False，也可以是字符串或其他 JSON 值
    """

    value: bool | str | int | float | None = True


class ChatRequest(BaseModel):
    """
    对话请求
    Attributes:
        message: 用户消息（含 @ 引用展开，供 Agent 使用）
        display_message: 对话框展示用短文本（不含引用块）；缺省时与 message 相同
        field_values: 前端当前编辑中的字段值（避免编辑中内容被旧缓存覆盖）
    """

    message: str
    display_message: str = ""
    field_values: dict[str, str] = {}


class RestoreBackupRequest(BaseModel):
    """
    恢复备份请求
    Attributes:
        timestamp: ISO 格式的时间戳，标识要恢复的备份版本
    """

    timestamp: str
