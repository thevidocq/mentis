# General Knowledge Base

The **General Knowledge Base** holds **general knowledge** used in the answers of every customer: how to handle a type of threat, SOC-wide playbooks, best practices, tool guides.

It must contain **no customer context**: no customer names, contacts, systems, escalation chains. Those go in the customer's own documents, which can be more specific and win when the two disagree.

## Who reads it

Everyone: every tenant admin and analyst uses it in the chat, nothing to tick. A customer can turn it off for all its chats (Settings → Include the General Knowledge Base), and an analyst can turn it off for a single chat with the **Knowledge Base** chip.

## Who manages it

The super-admin does not upload documents. Tick **Can manage the General Knowledge Base** (Users → edit or invite a tenant admin) only for the SOC admins who maintain it. It is off by default; "All customers" does not include it. A tenant admin who manages it can give the same permission to other tenant admins.

Those admins pick **General Knowledge Base** in the customer selector and use the **Documents** page. **Every new version needs approval** before it is used, because it reaches every customer. Every upload, approval and deletion is recorded in **Logs** with the user's name.
