import asyncio
import httpx
import os
import re
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from typing import TypedDict

load_dotenv()

class CopilotStudioDirectLine:
    def __init__(
        self,
        secret: str,
        user_id: str = "dl_langgraph-user",
        directline_base_url: str = "https://directline.botframework.com/v3/directline",
    ):
        self.secret = secret
        self.user_id = user_id
        self.directline_base_url = directline_base_url.rstrip("/")
        self.token = None
        self.conversation_id = None
        self.watermark = None
    
    @property
    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}
    
    async def _ensure_token(self, client: httpx.AsyncClient):
        if self.token:
            return
        
        # Exchange the long-lived web channel secret for a short-lived Direct Line
        # token, bound to a stable user id. The secret is only ever used here to
        # mint a scoped token; per-conversation calls use the token instead.
        token_response = await client.post(
            f"{self.directline_base_url}/tokens/generate",
            headers={"Authorization": f"Bearer {self.secret}"},
            json={"user": {"id": self.user_id}},
        )
        token_response.raise_for_status()
        self.token = token_response.json()["token"]
    
    async def _ensure_conversation(self):
        if self.conversation_id:
            return
        
        async with httpx.AsyncClient(timeout=30) as client:
            await self._ensure_token(client)
            headers = self._auth_headers
            
            # Start the conversation explicitly using the Direct Line token. This
            # returns an active conversationId scoped to the token; posting
            # activities to it avoids the 404s seen with an unstarted conversation.
            start_response = await client.post(
                f"{self.directline_base_url}/conversations",
                headers=headers,
            )
            start_response.raise_for_status()
            self.conversation_id = start_response.json()["conversationId"]
            
            # Copilot Studio ignores user messages until the conversation is kicked
            # off with a startConversation event (this is what the web chat control
            # sends). Without it the agent never replies.
            await client.post(
                f"{self.directline_base_url}/conversations/{self.conversation_id}/activities",
                headers=headers,
                json={
                    "type": "event",
                    "name": "startConversation",
                    "from": {"id": self.user_id, "name": "LangGraph workflow"},
                    "locale": "en-US",
                },
            )
            
            # Drain the agent's greeting so its watermark is passed; otherwise the
            # greeting would be returned as the answer to the first question.
            for _ in range(15):
                params = {"watermark": self.watermark} if self.watermark else {}
                data = (
                    await client.get(
                        f"{self.directline_base_url}/conversations/{self.conversation_id}/activities",
                        headers=headers,
                        params=params,
                    )
                ).json()
                self.watermark = data.get("watermark", self.watermark)
                if any(
                    a.get("type") == "message"
                    and a.get("from", {}).get("id") != self.user_id
                    and a.get("text")
                    for a in data.get("activities", [])
                ):
                    break
                await asyncio.sleep(1)
    
    async def ask(self, message: str) -> str:
        await self._ensure_conversation()
        
        headers = self._auth_headers
        
        activity = {
            "type": "message",
            "from": {"id": self.user_id, "name": "LangGraph workflow"},
            "text": message,
            "textFormat": "plain",
            "locale": "en-US",
        }
        
        async with httpx.AsyncClient(timeout=30) as client:
            post_response = await client.post(
                f"{self.directline_base_url}/conversations/{self.conversation_id}/activities",
                headers=headers,
                json=activity,
            )
            post_response.raise_for_status()
            
            # Poll until the Copilot Studio agent responds.
            for _ in range(30):
                params = {}
                if self.watermark:
                    params["watermark"] = self.watermark
                
                get_response = await client.get(
                    f"{self.directline_base_url}/conversations/{self.conversation_id}/activities",
                    headers=headers,
                    params=params,
                )
                get_response.raise_for_status()
                data = get_response.json()
                
                self.watermark = data.get("watermark", self.watermark)
                
                # Our user id is bound into the Direct Line token, so the agent's
                # messages are simply those whose from.id differs from ours.
                bot_messages = [
                    self._resolve_citations(a)
                    for a in data.get("activities", [])
                    if a.get("type") == "message"
                    and a.get("from", {}).get("id") != self.user_id
                    and a.get("text")
                ]
                
                if bot_messages:
                    return "\n".join(bot_messages)
                
                await asyncio.sleep(1)
        
        raise TimeoutError("No response from Copilot Studio agent.")
    
    @staticmethod
    def _resolve_citations(activity: dict) -> str:
        text = activity.get("text", "")
        
        # Copilot Studio exposes real source names in schema.org "Message"
        # entities; the message text itself only carries placeholder labels
        # (e.g. [1]: cite:1 "Citation-1"). Map citation position -> document name.
        citations: dict[int, str] = {}
        for entity in activity.get("entities", []):
            for claim in entity.get("citation", []) or []:
                position = claim.get("position")
                appearance = claim.get("appearance", {})
                name = appearance.get("name") or appearance.get("abstract")
                if position is not None and name:
                    citations[position] = name
        
        if not citations:
            return text
        
        # Drop the machine-generated markdown reference definitions like
        #   [1]: cite:1 "Citation-1"
        # and replace them with a readable Sources section using document names.
        text = re.sub(r'(?m)^\[\d+\]:\s*\S+\s*"[^"]*"\s*$', "", text).rstrip()
        sources = "\n".join(f"[{pos}] {citations[pos]}" for pos in sorted(citations))
        return f"{text}\n\nSources:\n{sources}"

class WorkflowState(TypedDict):
    user_request: str
    copilot_answer: str
    final_answer: str

copilot = CopilotStudioDirectLine(
    secret=os.environ["COPILOT_STUDIO_WEB_CHANNEL_SECRET"]
)

async def call_copilot_studio(state: WorkflowState) -> dict:
    answer = await copilot.ask(state["user_request"])
    return {"copilot_answer": answer}

async def finalize(state: WorkflowState) -> dict:
    # In a productrion workflow, this could be another LLM node, validator, router,
    # policy checker, human approval step, or CrewAI/LangGraph sub-workflow.
    return {
        "final_answer": (
            "Copilot Studio specialist agent returned:\n\n"
            f"{state['copilot_answer']}"
        )
    }

graph = StateGraph(WorkflowState)
graph.add_node("call_copilot_studio", call_copilot_studio)
graph.add_node("finalize", finalize)

graph.add_edge(START, "call_copilot_studio")
graph.add_edge("call_copilot_studio", "finalize")
graph.add_edge("finalize", END)

app = graph.compile()

async def main():
    result = await app.ainvoke(
        {"user_request": "What is the limit for a single taxi ride at Contoso Corp?"}
    )
    print(result["final_answer"])

if __name__ == "__main__":
    asyncio.run(main())
