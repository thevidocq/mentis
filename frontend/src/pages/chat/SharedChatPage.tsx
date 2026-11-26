import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { errorText } from "../../api/client";
import type { SharedChat } from "../../api/types";
import { Icon } from "../../components/Icon";
import { AssistantMessage, UserMessage } from "./MessageView";
import { SourcesPanel } from "./Sources";
import { chatApi } from "./chatApi";
import "./chat.css";

/** A chat shared by a colleague: read-only. */
export function SharedChatPage() {
  const { token = "" } = useParams();
  const [chat, setChat] = useState<SharedChat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sources, setSources] = useState<{ messageId: string; focus: number | null } | null>(null);

  useEffect(() => {
    chatApi.shared(token).then(setChat).catch((e) => setError(errorText(e)));
  }, [token]);

  const sourcesMessage = chat && sources ? chat.messages.find((m) => m.id === sources.messageId) : undefined;

  return (
    <div className="shell chat-shell">
      <main className="main chat-main shared-main">
        <header className="chat-head shared-head">
          <Link to="/chat" className="icon-btn" style={{ border: 0 }} aria-label="Back to your chats"><Icon name="chevronLeft" size={18} /></Link>
          <h1 className="chat-title">{chat?.title ?? "Shared chat"}</h1>
          {chat && <span className="pill accent"><Icon name="lock" size={12} /> {chat.scope_name}</span>}
          <span className="pill" style={{ marginLeft: "auto" }}>Read-only</span>
        </header>
        <div className="chat-scroll">
          <div className="chat-thread">
            {error && <div className="answer-error" role="alert"><Icon name="alert" /><div style={{ flex: 1 }}>{error}</div></div>}
            {!chat && !error && <p className="muted">Loading…</p>}
            {chat && (
              <div className="shared-banner small">
                <Icon name="share" size={16} />
                <span>Shared by <strong>{chat.owner_name}</strong>. You can read it and open its sources; you cannot add to it.</span>
              </div>
            )}
            {chat?.messages.map((m) =>
              m.role === "user" ? <UserMessage key={m.id} m={m} /> : (
                <AssistantMessage key={m.id} m={m} busy sourcesOpen={sources?.messageId === m.id}
                  onSources={(n) => setSources({ messageId: m.id, focus: n })} />
              ))}
            {chat && chat.hidden > 0 && (
              <p className="muted small">
                {chat.hidden === 1 ? "1 question and its answer are" : `${chat.hidden} questions and their answers are`} not shown:
                they used the documentation of a customer you do not see.
              </p>
            )}
          </div>
        </div>
      </main>
      {sourcesMessage && (
        <SourcesPanel key={sourcesMessage.id} citations={sourcesMessage.citations} focus={sources?.focus ?? null} onClose={() => setSources(null)} />
      )}
    </div>
  );
}
