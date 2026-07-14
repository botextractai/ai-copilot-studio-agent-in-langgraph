# Use a Copilot Studio agent inside an open source LangGraph workflow

Imagine taking the enterprise agents you already built in Microsoft Copilot Studio, with all their curated knowledge, business logic, and governance, and dropping them straight into open source agent frameworks like LangGraph or CrewAI. That is exactly what this example does: it turns a Copilot Studio agent into a plain, callable building block you can orchestrate alongside any other tool or model. Instead of choosing between Microsoft's platform and the flexibility of open source frameworks, you get both, reusing your governed Copilot Studio investments as specialist nodes inside your own workflows.

## About this example

This example shows how you can make a Copilot Studio agent a callable node/tool inside an open source workflow.

For your production agentic workflow, make `call_copilot_studio` one node among several: planner, retrieval, Copilot Studio specialist, verifier, human approval, final response. The Copilot Studio agent then becomes an enterprise-knowledge or business-process specialist rather than the overall orchestrator.

The following diagram shows the workflow implemented in `main.py`:

![Flowchart of the main.py workflow](https://github.com/user-attachments/assets/e7e620aa-f667-44de-b6cb-cf2922dfc96e "Flowchart of the main.py workflow")

## Copilot Studio's endpoint model: Direct Line

Copilot Studio doesn't give you a plain REST endpoint like a typical API. Instead, it exposes agents through the Direct Line API, part of the Bot Framework, which supports both HTTP requests and WebSocket connections for real-time message delivery.

To call an agent this way, `main.py` performs the following steps (see `CopilotStudioDirectLine`):

1. **Generate a short-lived token from the secret.** `POST /v3/directline/tokens/generate` with `Authorization: Bearer <COPILOT_STUDIO_WEB_CHANNEL_SECRET>`, binding a stable `user` id. The secret is only ever used here; every subsequent call uses the returned token.
2. **Start a conversation.** `POST /conversations` returns an active conversation id scoped to the token.
3. **Send a `startConversation` event, then skip the greeting.** This is an easy-to-miss requirement: Copilot Studio ignores user messages until it receives this event (it is what the web chat control sends). The agent's greeting is then drained via the `watermark` so it isn't mistaken for the answer to the first question.
4. **Post the question and poll for the reply.** Messages are sent as Bot Framework "activities"; responses are read by polling `/activities` with the `watermark`.
5. **Resolve citations.** Source document names live in the activity's schema.org `Message` entities (not in the message text, which only carries placeholders like `[1]: cite:1 "Citation-1"`). They are rendered into a readable `Sources:` list.

The Direct Line token is generated automatically at runtime and is short-lived (~1 hour), so there is no token to manage manually, only the secret in your `.env`.

## Copilot Studio requirement

For this example, you need access to Microsoft Copilot Studio through the Microsoft Power Platform. For a free trial, you'll need a valid Microsoft work or school account.

## Create a Copilot Studio agent

The user interface of Microsoft Copilot Studio changes frequently. The order of the following steps might change, but for this example, at a minimum, you need to give the agent a name (step 3), select a Large Language Model (step 4), provide instructions (step 5), and add a document to the knowledge base (step 6).

The following instructions apply to what Microsoft calls the "new experience" of Copilot Studio, as opposed to the previous "classic" experience. If you are already using the "new experience", then you might see a "new experience" toggle. If you are using the "classic" experience, then you might see a banner or card saying something like "New Copilot Studio experience" with a "Try now" button next to it that you should click.

1. Log in to Microsoft Copilot Studio: https://copilotstudio.microsoft.com
2. Start building a new agent from scratch.
3. Name the agent: `expense-agent`
4. Select a "Model", for example: `GPT-5 Chat`
5. In the "Instructions" section, enter the following text:

```
You are a helpful AI assistant who supports employees with expense claims.
Provide concise, accurate information only on topics related to expenses.
Do not provide any information about topics that are not directly related to expenses.
Base every answer on the provided knowledge sources and always include a citation to the source document you used. Do not write the document name in the answer text itself.
```

6. In the "Knowledge" section, upload the `expenses_policy.docx` file from this repository to the agent and click the "Add to agent" button.
7. Click the three dots "..." for more options -> "Settings" -> "AI & behavior" and set the "Moderation level" to "High" (or "Maximum" for the strictest matching). A higher moderation level forces the agent to require a strong match in your knowledge sources before answering, which reduces ungrounded/hallucinated responses. Close the dialog by clicking the "X".
8. Save the agent by clicking the "Save" icon (if it hasn't already been saved automatically).
9. Click the dropdown arrow next to "Publish", and publish the agent as "Web app" type. Click the "Publish" (or possibly "Save and Publish") button. Close the dialog by clicking the "X".
10. Click the three dots "..." for more options -> "Settings" -> "Safety & access" -> "Authentication" and select "No authentication".

> **Why "No authentication" still works here.** This example uses an uploaded file as the knowledge source, which is stored with the agent and served to anyone who can reach it, so no user sign-in is needed. Live sources like SharePoint are different: the agent accesses them on behalf of the signed-in end user (with that user's own permissions), so they require authentication and return nothing under "No authentication". For anything sensitive, use "Authenticate with Microsoft" and a source such as SharePoint so each user only sees what they are allowed to.

11. In the same dialog as in the previous step, expand "Web channel security".
12. Click "Copy" to copy one of the two secrets into your clipboard. Copy `.env.example` to `.env` and set `COPILOT_STUDIO_WEB_CHANNEL_SECRET` to this secret. This is the value `main.py` reads (via `os.environ["COPILOT_STUDIO_WEB_CHANNEL_SECRET"]`) to generate a Direct Line token.
13. Still in the same dialog, toggle "Require secured access" **on** and confirm this by clicking the "Enable" button. This is what makes the web channel secret required, so the token-generation flow above works. Close the dialog by clicking the "X".
14. Save the agent again by clicking the "Save" icon (if it hasn't already been saved automatically).
15. Re-publish the agent again (in some cases, this might have to be repeated multiple times until it works correctly):

> **Re-publish after every change (repeat step 9).** The Copilot Studio Playground always runs your latest in-editor edits, but the Direct Line "Web app" channel that `main.py` calls only serves the **last published version**. If answers from `main.py` look worse than the Playground, re-publish the agent (step 9).

## Run the workflow

1. Install the requirements:

   ```bash
   pip install -r requirements.txt
   ```

2. Run this example:
   ```bash
   python main.py
   ```

## Example result

`main.py` sends a sample expense question through the LangGraph workflow to the Copilot Studio agent and prints the agent's answer, including a `Sources:` list resolved from the response's citations.

The example question is:

```
What is the limit for a single taxi ride at Contoso Corp?
```

One possible example answer is:

```
Copilot Studio specialist agent returned:

The limit for a single taxi (or rideshare) ride at Contoso Corp. is **$75 per ride**, and it must cover a distance of more than one mile[1].

Sources:
[1] expenses_policy.docx
```
