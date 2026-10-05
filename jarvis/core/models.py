from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

# --- Tool Execution Models ---

class ToolCallRequest(BaseModel):
    id: str = Field(..., description="Unique ID for this tool call from the LLM")
    name: str = Field(..., description="Name of the tool to execute")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Parsed arguments for the tool")

class ToolResult(BaseModel):
    tool_call_id: str
    name: str
    content: str
    error: bool = False

# --- Context & Telemetry Models ---

class SystemVitals(BaseModel):
    battery_percent: int
    battery_charging: bool
    # Memory in MB
    ram_used: int
    ram_total: int
    cpu_load_percent: float
    cpu_temp_c: Optional[float] = None
    
class HyprlandState(BaseModel):
    active_workspace: int
    active_window_title: str
    active_window_class: str
    monitors: List[Dict[str, Any]] = Field(default_factory=list)

class LiveContext(BaseModel):
    vitals: SystemVitals
    hyprland: HyprlandState
    clipboard: str = ""
    last_user_input_time: float

# --- LLM Response Models ---

class JarvisResponse(BaseModel):
    text: str = Field(..., description="Spoken/printed response to the user")
    tool_calls: List[ToolCallRequest] = Field(default_factory=list)
    
class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

class ChatMessage(BaseModel):
    role: MessageRole
    content: Union[str, List[Dict[str, Any]]] # string or multimodal blocks
    tool_call_id: Optional[str] = None # When role=TOOL
    name: Optional[str] = None # Usually the tool name
    tool_calls: Optional[List[Dict[str, Any]]] = None # Raw tool calls from assistant

