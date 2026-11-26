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
import { ShareDialog } from "./ShareDialog";
import { SourcesPanel } from "./Sources";
import "./chat.css";

export function ChatPage() {
  const { chatId } = useParams();
  const navigate = useNavigate();
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [query, setQuery] = useState("");
  const [scopes, setScopes] = useState<ScopeOption[]>([]);
  const [scopesLoaded, setScopesLoaded] = useState(false);
  const [draftScope, setDraftScope] = useState<ScopeOption | null>(null);
  const [draftGeneral, setDraftGeneral] = useState(true); // on by default; turned off only explicitly
  const [chat, setChat] = useState<ChatFull | null>(null);
  // Sources panel on the right: the answer whose sources are shown, and the section in focus.
  const [sources, setSources] = useState<{ messageId: string; focus: number | null } | null>(null);
  const [pending, setPending] = useState<{ text: string; chat: string | undefined } | null>(null); // question waiting for its answer
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const [drawer, setDrawer] = useState(false);
  const [sharing, setSharing] = useState(false);
  useEffect(() => { setDrawer(false); setSources(null); }, [chatId]); // another chat: close the menu and the sources panel

  const refreshList = useCallback((q: string) => chatApi.list(q).then(setChats).catch(() => undefined), []);

  useEffect(() => {
    chatApi.scopes().then((s) => { setScopes(s); setScopesLoaded(true); setDraftScope((d) => d ?? s[0] ?? null); }).catch((e) => setError(errorText(e)));
  }, []);

  useEffect(() => {
    const t = setTimeout(() => refreshList(query), 200);
    return () => clearTimeout(t);
  }, [query, refreshList]);

  // The chat on screen. An answer or a chat load that arrives after the user moved to another chat
  // must not land in (or replace) the one now shown: the next question would go to the wrong chat.
  const shown = useRef<string | undefined>(chatId);
  shown.current = chatId;

  useEffect(() => {
    setError(null);
    if (!chatId) { setChat(null); return; }
    if (chat?.id === chatId) return;
    setChat(null);
    chatApi.get(chatId)
      .then((c) => { if (shown.current === chatId) setChat(c); })
      .catch(() => { if (shown.current === chatId) navigate("/chat", { replace: true }); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId]);

  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [chat?.messages.length, pending]);

  const loadingChat = !!chatId && chat?.id !== chatId;
  const pendingHere = pending && pending.chat === chatId ? pending.text : null;
  const locked = !!chat;
  const scope: ScopeOption | null = chat ? { id: chat.scope_tenant_id, name: chat.scope_name } : draftScope;
  const unavailable = chat && !chat.scope_available ? "This customer is no longer available. Start a new chat." : undefined;

  // The General Knowledge Base switch: before the first question it is part of the new chat; after,
  // it applies to the next questions of this chat.
  async function setUseGeneral(v: boolean) {
    if (!chat) return setDraftGeneral(v);
    try {
      const s = await chatApi.setGeneral(chat.id, v);
      setChat((c) => (c && c.id === s.id ? { ...c, use_general: s.use_general } : c));
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function send(text: string) {
    if (pending || loadingChat) return;
    const from = chatId;
    setPending({ text, chat: from });
    setError(null);
    try {
      if (!chat) {
        const ex = await chatApi.create(draftScope?.id ?? null, text, draftGeneral);
        if (shown.current === from) {
          setChat({ ...ex.chat, scope_available: true, messages: [ex.question, ex.answer] });
          navigate(`/chat/${ex.chat.id}`);
        }
      } else {
        const ex = await chatApi.ask(chat.id, text);
        setChat((c) => (c && c.id === ex.chat.id ? { ...c, ...ex.chat, messages: [...c.messages, ex.question, ex.answer] } : c));
      }
      refreshList(query);
    } catch (e) {
      if (shown.current === from) setError(errorText(e));
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
    setDraftGeneral(true);

    navigate("/chat");
  }

  const messages = chat?.messages ?? [];
  const scopeLabel = scope?.id ? scope.name : "all customers";

  const sourcesMessage = sources ? messages.find((m) => m.id === sources.messageId && m.role === "assistant") : undefined;

  return (
    <div className={`shell chat-shell${drawer ? " drawer-open" : ""}${sourcesMessage ? " sources-open" : ""}`}>
      <MobileBar title={chat?.title ?? "New chat"} onMenu={() => setDrawer(true)}
        right={<>
          {chat && <button className="icon-btn" style={{ border: 0 }} aria-label="Share chat" onClick={() => setSharing(true)}><Icon name="share" size={19} /></button>}
          <button className="icon-btn" style={{ border: 0 }} aria-label="New chat" onClick={newChat}><Icon name="plus" size={20} /></button>
        </>} />
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
            <span className="chat-scope" title={locked ? "Customer locked for this chat" : "Customer for this chat"}>
              {locked && <Icon name="lock" size={13} />}{scope.name}
            </span>
          )}
          {chat && (
            <button className="btn btn-sm chat-share-btn" onClick={() => setSharing(true)} title="Share a read-only link with colleagues">
              <Icon name="share" size={15} />{chat.shared ? "Shared" : "Share"}
            </button>
          )}
        </header>
        <div className="chat-scroll">
          <div className="chat-thread">
            {messages.length === 0 && !pendingHere && !loadingChat && (
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
                  sourcesOpen={sources?.messageId === m.id}
                  onSources={(n) => setSources({ messageId: m.id, focus: n })}
                  onRetry={i === messages.length - 1 && messages[i - 1] ? () => send(messages[i - 1].content) : undefined} />
              ))}
            {pendingHere && <><UserMessage m={{ content: pendingHere }} /><Thinking scope={scopeLabel} /></>}
            {error && <div className="answer-error" role="alert"><Icon name="alert" /><div style={{ flex: 1 }}>{error}</div></div>}
            <div ref={end} />
          </div>
        </div>
        <div className="chat-bottom">
          <Composer scopes={scopes} scope={scope} locked={locked} disabled={!!pending || loadingChat || !!unavailable} disabledReason={unavailable}
            onScope={setDraftScope} onSend={send}
            useGeneral={chat ? chat.use_general !== false : draftGeneral} onUseGeneral={setUseGeneral} />
          <div className="muted small chat-disclaimer">Mentis answers only from the documents in use. Check the sources before acting.</div>
        </div>
      </main>
      {sharing && chat && (
        <ShareDialog chatId={chat.id} onClose={() => setSharing(false)}
          onChange={(shared) => setChat((c) => (c && c.id === chat.id ? { ...c, shared } : c))} />
      )}
      {sourcesMessage && (
        <SourcesPanel key={sourcesMessage.id} citations={sourcesMessage.citations} focus={sources?.focus ?? null} onClose={() => setSources(null)} />
      )}
    </div>
  );
}
