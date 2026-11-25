import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { errorText } from "../../api/client";
import type { ChatFull, ChatMessage, ChatSummary, ScopeOption } from "../../api/types";
import { MobileBar } from "../../layouts/AdminShell";
import { Icon } from "../../components/Icon";
import { chatApi } from "./chatApi";
import { ChatSidebar } from "./ChatSidebar";
import { Composer } from "./Composer";
import { AssistantMessage, Thinking, UserMessage } from "./MessageView";
import "./chat.css";

export function ChatPage() {
  const { chatId } = useParams();
  const navigate = useNavigate();
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [query, setQuery] = useState("");
  const [scopes, setScopes] = useState<ScopeOption[]>([]);
  const [scopesLoaded, setScopesLoaded] = useState(false);
  const [draftScope, setDraftScope] = useState<ScopeOption | null>(null);
  const [chat, setChat] = useState<ChatFull | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const [drawer, setDrawer] = useState(false);
  useEffect(() => setDrawer(false), [chatId]);

  const refreshList = useCallback((q: string) => chatApi.list(q).then(setChats).catch(() => undefined), []);

  useEffect(() => {
    chatApi.scopes().then((s) => { setScopes(s); setScopesLoaded(true); setDraftScope((d) => d ?? s[0] ?? null); }).catch((e) => setError(errorText(e)));
  }, []);

  useEffect(() => {
    const t = setTimeout(() => refreshList(query), 200);
    return () => clearTimeout(t);
  }, [query, refreshList]);

  useEffect(() => {
    setError(null);
    if (!chatId) { setChat(null); return; }
    if (chat?.id === chatId) return;
    chatApi.get(chatId).then(setChat).catch(() => { setChat(null); navigate("/chat", { replace: true }); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId]);

  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [chat?.messages.length, pending]);

  const locked = !!chat;
  const scope: ScopeOption | null = chat ? { id: chat.scope_tenant_id, name: chat.scope_name } : draftScope;
  const unavailable = chat && !chat.scope_available ? "This customer is no longer available. Start a new chat." : undefined;

  async function send(text: string) {
    if (pending) return;
    setPending(text);
    setError(null);
    try {
      if (!chat) {
        const ex = await chatApi.create(draftScope?.id ?? null, text);
        setChat({ ...ex.chat, scope_available: true, messages: [ex.question, ex.answer] });
        navigate(`/chat/${ex.chat.id}`);
      } else {
        const ex = await chatApi.ask(chat.id, text);
        setChat((c) => (c ? { ...c, ...ex.chat, messages: [...c.messages, ex.question, ex.answer] } : c));
      }
      refreshList(query);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setPending(null);
    }
  }

  async function feedback(m: ChatMessage, value: 1 | -1 | null) {
    if (!chat) return;
    const prev = m.feedback;
    const patch = (v: 1 | -1 | null) => setChat((c) => c && { ...c, messages: c.messages.map((x) => (x.id === m.id ? { ...x, feedback: v } : x)) });
    patch(value);
    try { await chatApi.feedback(chat.id, m.id, value); } catch (e) { patch(prev); setError(errorText(e)); }
  }

  function newChat() {
    setChat(null);
    setError(null);
    setDraftScope(scopes[0] ?? null); // every new chat starts on the first option (all your customers, when you have several)

    navigate("/chat");
  }

  const messages = chat?.messages ?? [];
  const scopeLabel = scope?.id ? scope.name : "all customers";

  return (
    <div className={`shell chat-shell${drawer ? " drawer-open" : ""}`}>
      <MobileBar title={chat?.title ?? "New chat"} onMenu={() => setDrawer(true)}
        right={<button className="icon-btn" style={{ border: 0 }} aria-label="New chat" onClick={newChat}><Icon name="plus" size={20} /></button>} />
      <div className="drawer-backdrop" onClick={() => setDrawer(false)} aria-hidden="true" />
      <ChatSidebar chats={chats} query={query} onQuery={setQuery} onNew={() => { newChat(); setDrawer(false); }} onClose={() => setDrawer(false)}
        onRename={async (id, title) => {
          const s = await chatApi.rename(id, title);
          setChats((cs) => cs.map((c) => (c.id === id ? s : c)));
          setChat((c) => (c && c.id === id ? { ...c, title: s.title } : c));
        }}
        onDelete={async (id) => {
          await chatApi.remove(id);
          setChats((cs) => cs.filter((c) => c.id !== id));
          if (chat?.id === id) newChat();
        }} />
      <main className="main chat-main">
        <header className="chat-head">
          <h1 className="chat-title">{chat?.title ?? "New chat"}</h1>
          {scope && (
            <span className={`pill${scope.id ? " accent" : ""}`} title={locked ? "Customer locked for this chat" : "Customer for this chat"}>
              {locked && <Icon name="lock" size={12} />} {scope.name}
            </span>
          )}
        </header>
        <div className="chat-scroll">
          <div className="chat-thread">
            {messages.length === 0 && !pending && (
              <div className="chat-empty">
                <span style={{ color: "var(--accent-text)" }}><Icon name="chat" size={36} /></span>
                <h2>Ask about a customer's procedures</h2>
                {!scopesLoaded ? null : scopes.length === 0 ? (
                  <p className="muted">No customer is assigned to you yet. Ask your tenant admin to give you access to a customer.</p>
                ) : (
                  <p className="muted">
                    {scopes.length > 1 ? <>Choose the customer with <strong>@</strong> (or keep <strong>{scopes[0].name}</strong>), then ask. </> : <>Ask about <strong>{scopes[0].name}</strong>. </>}
                    Answers come only from the documentation in use, with the source of every statement. The customer stays fixed for the whole chat.
                  </p>
                )}
                <p className="muted small">You see only the customers assigned to you.</p>
              </div>
            )}
            {messages.map((m, i) =>
              m.role === "user" ? <UserMessage key={m.id} m={m} /> : (
                <AssistantMessage key={m.id} m={m} busy={!!pending || !!unavailable} onFollowup={send}
                  onFeedback={(v) => feedback(m, v)}
                  onRetry={i === messages.length - 1 && messages[i - 1] ? () => send(messages[i - 1].content) : undefined} />
              ))}
            {pending && <><UserMessage m={{ content: pending }} /><Thinking scope={scopeLabel} /></>}
            {error && <div className="answer-error" role="alert"><Icon name="alert" /><div style={{ flex: 1 }}>{error}</div></div>}
            <div ref={end} />
          </div>
        </div>
        <div className="chat-bottom">
          <Composer scopes={scopes} scope={scope} locked={locked} disabled={!!pending || !!unavailable} disabledReason={unavailable}
            onScope={setDraftScope} onSend={send} />
          <div className="muted small chat-disclaimer">Mentis answers only from the documents in use. Check the sources before acting.</div>
        </div>
      </main>
    </div>
  );
}
