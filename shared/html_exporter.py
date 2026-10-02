import html
import json
import os
from typing import Any, Dict, List, Optional


def build_telegram_html_viewer(
    account_info: Dict[str, Any],
    chats_data: List[Dict[str, Any]],
    folders_data: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Generates a standalone, Telegram-styled interactive HTML viewer
    that supports browsing all chats, viewing photos, playing audio/voice messages,
    watching video notes (кружки), and filtering by Telegram folders.
    """
    name = html.escape(str(account_info.get("name", "Пользователь")))
    phone = html.escape(str(account_info.get("phone", "—")))
    user_id = html.escape(str(account_info.get("id", "—")))
    date_str = html.escape(str(account_info.get("date", "—")))

    # Convert chats and folders data to JSON for client-side rendering
    chats_json = json.dumps(chats_data, ensure_ascii=False)
    folders_json = json.dumps(folders_data or [], ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Архив Telegram | {name}</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }}
        body {{
            background: #0f141c;
            color: #f5f5f5;
            height: 100vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}
        /* Top Navigation */
        .header {{
            background: #17212b;
            padding: 12px 20px;
            border-bottom: 1px solid #232e3c;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }}
        .header-title {{
            font-size: 16px;
            font-weight: 600;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .badge-tg {{
            background: #2481cc;
            color: #fff;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: bold;
        }}
        .header-meta {{
            font-size: 13px;
            color: #7f91a4;
        }}
        .header-meta span {{
            color: #4daafc;
            font-weight: 500;
        }}

        /* Main Workspace */
        .workspace {{
            display: flex;
            flex: 1;
            height: calc(100vh - 50px);
            overflow: hidden;
        }}

        /* Sidebar Chats List */
        .sidebar {{
            width: 340px;
            background: #17212b;
            border-right: 1px solid #232e3c;
            overflow-y: auto;
            flex-shrink: 0;
            display: flex;
            flex-direction: column;
        }}
        .search-box {{
            padding: 10px 14px;
            border-bottom: 1px solid #232e3c;
        }}
        .search-input {{
            width: 100%;
            padding: 8px 12px;
            background: #242f3d;
            border: 1px solid #324153;
            border-radius: 8px;
            color: #fff;
            font-size: 13px;
            outline: none;
        }}
        .search-input:focus {{
            border-color: #2481cc;
        }}
        .folders-container {{
            display: flex;
            align-items: center;
            position: relative;
            background: #17212b;
            border-bottom: 1px solid #232e3c;
            width: 100%;
            min-width: 0;
            flex-shrink: 0;
        }}
        .folder-arrow-btn {{
            display: none;
            width: 22px;
            height: 38px;
            background: rgba(23, 33, 43, 0.95);
            color: #7f91a4;
            border: none;
            cursor: pointer;
            font-size: 20px;
            line-height: 1;
            align-items: center;
            justify-content: center;
            z-index: 3;
            transition: color 0.15s, background 0.15s;
            flex-shrink: 0;
            padding: 0;
            user-select: none;
        }}
        .folder-arrow-btn:hover {{
            color: #fff;
            background: rgba(36, 129, 204, 0.35);
        }}
        .folders-bar {{
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 8px 10px;
            overflow-x: auto;
            white-space: nowrap;
            width: 100%;
            min-width: 0;
            flex: 1;
            scrollbar-width: none;
            -ms-overflow-style: none;
            -webkit-overflow-scrolling: touch;
            touch-action: pan-x;
            overscroll-behavior-x: contain;
            cursor: grab;
            scroll-behavior: smooth;
        }}
        .folders-bar::-webkit-scrollbar {{
            display: none;
        }}
        .folders-bar.dragging {{
            cursor: grabbing !important;
            user-select: none;
            scroll-behavior: auto;
        }}
        .folder-tab {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 5px 11px;
            border-radius: 14px;
            font-size: 12px;
            font-weight: 500;
            color: #7f91a4;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.05);
            cursor: pointer;
            transition: all 0.15s ease;
            user-select: none;
            flex-shrink: 0;
        }}
        .folder-tab:hover {{
            color: #fff;
            background: rgba(255, 255, 255, 0.09);
        }}
        .folder-tab.active {{
            color: #fff;
            background: #2481cc;
            font-weight: 600;
            border-color: #2481cc;
            box-shadow: 0 2px 6px rgba(36, 129, 204, 0.35);
        }}
        .folder-badge {{
            font-size: 10px;
            padding: 1px 5px;
            border-radius: 8px;
            background: rgba(0, 0, 0, 0.3);
            color: inherit;
        }}
        .folder-tab.active .folder-badge {{
            background: rgba(255, 255, 255, 0.25);
            color: #fff;
        }}
        .chats-list {{
            flex: 1;
            overflow-y: auto;
        }}
        .chat-item {{
            padding: 12px 16px;
            border-bottom: 1px solid #1e2a38;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 12px;
            transition: background 0.15s;
        }}
        .chat-item:hover {{
            background: #202b36;
        }}
        .chat-item.active {{
            background: #2b5278;
        }}
        .avatar {{
            width: 44px;
            height: 44px;
            border-radius: 50%;
            background: #2f6ea5;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            font-size: 16px;
            flex-shrink: 0;
            color: #fff;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }}
        .chat-item.saved .avatar {{
            background: #0088cc;
        }}
        .chat-info {{
            flex: 1;
            overflow: hidden;
        }}
        .chat-name-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 4px;
        }}
        .chat-name {{
            font-size: 14px;
            font-weight: 600;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            color: #fff;
        }}
        .chat-badges {{
            display: flex;
            align-items: center;
            gap: 4px;
            flex-shrink: 0;
        }}
        .chat-photo-badge {{
            font-size: 10px;
            background: rgba(36, 129, 204, 0.25);
            color: #64b5f6;
            border: 1px solid rgba(100, 181, 246, 0.3);
            padding: 1px 5px;
            border-radius: 8px;
            font-weight: 600;
        }}
        .chat-count {{
            font-size: 11px;
            background: #242f3d;
            padding: 2px 6px;
            border-radius: 10px;
            color: #7f91a4;
        }}
        .chat-preview {{
            font-size: 12px;
            color: #7f91a4;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        /* Chat Viewport */
        .chat-viewport {{
            flex: 1;
            background: #0e1621;
            display: flex;
            flex-direction: column;
            height: 100%;
            position: relative;
        }}
        .active-chat-header {{
            background: #17212b;
            padding: 12px 20px;
            border-bottom: 1px solid #232e3c;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }}
        .active-chat-title {{
            font-size: 15px;
            font-weight: 600;
            color: #fff;
        }}
        .active-chat-sub {{
            font-size: 12px;
            color: #7f91a4;
            margin-top: 2px;
        }}

        /* Messages */
        .messages-scroll {{
            flex: 1;
            overflow-y: auto;
            padding: 20px 24px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }}
        .empty-state {{
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: #5d6f80;
            font-size: 15px;
            flex-direction: column;
            gap: 10px;
        }}
        .msg-bubble {{
            max-width: 68%;
            padding: 10px 14px;
            border-radius: 12px;
            font-size: 14px;
            line-height: 1.45;
            word-break: break-word;
            position: relative;
            box-shadow: 0 1px 2px rgba(0,0,0,0.25);
            display: flex;
            flex-direction: column;
        }}
        .msg-bubble.in {{
            align-self: flex-start;
            background: #182533;
            color: #fff;
            border-bottom-left-radius: 3px;
        }}
        .msg-bubble.out {{
            align-self: flex-end;
            background: #2b5278;
            color: #fff;
            border-bottom-right-radius: 3px;
        }}
        .msg-sender {{
            font-size: 12px;
            font-weight: 600;
            color: #64b5f6;
            margin-bottom: 4px;
        }}
        .msg-bubble.out .msg-sender {{
            color: #b3e5fc;
        }}
        .msg-text {{
            white-space: pre-wrap;
        }}
        .msg-placeholder {{
            font-style: italic;
            color: #8da4be;
            font-size: 13px;
            display: inline-flex;
            align-items: center;
            gap: 5px;
            opacity: 0.85;
        }}
        .msg-meta {{
            font-size: 10px;
            color: rgba(255,255,255,0.45);
            text-align: right;
            margin-top: 6px;
        }}

        /* Media */
        .msg-photo-wrap {{
            margin-top: 6px;
            border-radius: 8px;
            overflow: hidden;
            max-width: 320px;
        }}
        .msg-photo-wrap img {{
            width: 100%;
            height: auto;
            display: block;
            cursor: pointer;
            transition: transform 0.2s;
        }}
        .msg-photo-wrap img:hover {{
            transform: scale(1.02);
        }}
        .msg-voice-wrap {{
            margin-top: 6px;
            display: flex;
            align-items: center;
            gap: 8px;
            background: rgba(0,0,0,0.25);
            padding: 4px 10px;
            border-radius: 20px;
            max-width: 100%;
            width: fit-content;
        }}
        .msg-voice-wrap audio {{
            height: 34px;
            max-width: 250px;
            outline: none;
        }}
        .media-dl-btn {{
            color: #4daafc;
            text-decoration: none;
            font-size: 14px;
            padding: 3px 6px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(36, 129, 204, 0.2);
            transition: background 0.2s;
        }}
        .media-dl-btn:hover {{
            background: rgba(36, 129, 204, 0.45);
        }}
        .msg-circle-wrap {{
            margin-top: 6px;
            width: 200px;
            height: 200px;
            border-radius: 50%;
            overflow: hidden;
            box-shadow: 0 4px 12px rgba(0,0,0,0.5);
            border: 2px solid #2481cc;
            position: relative;
            background: #000;
        }}
        .msg-circle-wrap video {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            border-radius: 50%;
        }}
        .media-error-badge {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 10px;
            background: rgba(255, 68, 68, 0.12);
            border: 1px dashed rgba(255, 68, 68, 0.4);
            border-radius: 8px;
            color: #ff8080;
            font-size: 11px;
            margin-top: 6px;
        }}
    </style>
</head>
<body>

    <!-- Top Header -->
    <div class="header">
        <div class="header-title">
            <span class="badge-tg">TELEGRAM DUMP</span>
            <span>{name}</span>
        </div>
        <div class="header-meta">
            📱 Телефон: <span>+{phone.lstrip('+')}</span> &nbsp;|&nbsp; 🆔 ID: <span>{user_id}</span> &nbsp;|&nbsp; ⏱ <span>{date_str}</span>
        </div>
    </div>

    <!-- Main Workspace -->
    <div class="workspace">
        <!-- Sidebar -->
        <div class="sidebar">
            <div class="search-box">
                <input type="text" class="search-input" id="searchChats" placeholder="Поиск чата..." oninput="filterChats()">
            </div>
            <div class="folders-container" id="foldersContainer" style="display: none;">
                <button type="button" class="folder-arrow-btn" id="folderArrowLeft" onclick="scrollFolders(-140)" title="Влево">‹</button>
                <div class="folders-bar" id="foldersBar"></div>
                <button type="button" class="folder-arrow-btn" id="folderArrowRight" onclick="scrollFolders(140)" title="Вправо">›</button>
            </div>
            <div class="chats-list" id="chatsList"></div>
        </div>

        <!-- Chat Viewport -->
        <div class="chat-viewport">
            <div class="active-chat-header" id="chatHeader" style="display: none;">
                <div>
                    <div class="active-chat-title" id="activeChatName"></div>
                    <div class="active-chat-sub" id="activeChatSub"></div>
                </div>
            </div>
            <div class="messages-scroll" id="messagesScroll">
                <div class="empty-state">
                    <div>💬 Выберите диалог слева для просмотра сообщений и медиа</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const chatsData = {chats_json};
        const foldersData = {folders_json};
        let activeFolderId = "all";
        let activeChatIndex = 0;

        function scrollFolders(amount) {{
            const bar = document.getElementById("foldersBar");
            if (!bar) return;
            bar.scrollBy({{ left: amount, behavior: "smooth" }});
            setTimeout(updateFolderArrows, 220);
        }}

        function updateFolderArrows() {{
            const bar = document.getElementById("foldersBar");
            const leftBtn = document.getElementById("folderArrowLeft");
            const rightBtn = document.getElementById("folderArrowRight");
            if (!bar || !leftBtn || !rightBtn) return;

            const canScroll = bar.scrollWidth > bar.clientWidth + 2;
            if (!canScroll) {{
                leftBtn.style.display = "none";
                rightBtn.style.display = "none";
                return;
            }}

            leftBtn.style.display = bar.scrollLeft > 4 ? "flex" : "none";
            const maxScrollLeft = bar.scrollWidth - bar.clientWidth - 4;
            rightBtn.style.display = bar.scrollLeft < maxScrollLeft ? "flex" : "none";
        }}

        let folderScrollInitialized = false;
        function setupFolderScroll() {{
            if (folderScrollInitialized) return;
            folderScrollInitialized = true;
            const bar = document.getElementById("foldersBar");
            if (!bar) return;

            // 1. Mouse wheel: convert deltaY to horizontal scroll
            bar.addEventListener("wheel", (e) => {{
                if (e.deltaY !== 0) {{
                    e.preventDefault();
                    bar.scrollLeft += e.deltaY;
                    updateFolderArrows();
                }}
            }}, {{ passive: false }});

            // 2. Drag-to-scroll with mouse
            let isDown = false;
            let startX = 0;
            let startScroll = 0;
            let hasDragged = false;

            bar.addEventListener("mousedown", (e) => {{
                isDown = true;
                hasDragged = false;
                bar.classList.add("dragging");
                startX = e.pageX - bar.offsetLeft;
                startScroll = bar.scrollLeft;
            }});

            window.addEventListener("mouseup", () => {{
                if (isDown) {{
                    isDown = false;
                    bar.classList.remove("dragging");
                }}
            }});

            bar.addEventListener("mousemove", (e) => {{
                if (!isDown) return;
                const x = e.pageX - bar.offsetLeft;
                const walk = (x - startX) * 1.4;
                if (Math.abs(walk) > 4) {{
                    hasDragged = true;
                }}
                bar.scrollLeft = startScroll - walk;
                updateFolderArrows();
            }});

            bar.addEventListener("click", (e) => {{
                if (hasDragged) {{
                    e.stopPropagation();
                    hasDragged = false;
                }}
            }}, true);

            bar.addEventListener("scroll", updateFolderArrows);
            window.addEventListener("resize", updateFolderArrows);
        }}

        function initFolders() {{
            const container = document.getElementById("foldersContainer");
            const bar = document.getElementById("foldersBar");
            if (!foldersData || foldersData.length <= 1) {{
                if (container) container.style.display = "none";
                return;
            }}
            container.style.display = "flex";
            bar.innerHTML = "";

            foldersData.forEach(folder => {{
                const tab = document.createElement("button");
                const isAct = String(folder.id) === String(activeFolderId);
                tab.className = "folder-tab" + (isAct ? " active" : "");
                tab.onclick = () => selectFolder(folder.id);

                const iconHtml = folder.emoticon ? `<span>${{escapeHtml(folder.emoticon)}}</span>` : "";
                const countBadge = folder.count !== undefined ? `<span class="folder-badge">${{folder.count}}</span>` : "";

                tab.innerHTML = `${{iconHtml}}<span>${{escapeHtml(folder.title)}}</span>${{countBadge}}`;
                bar.appendChild(tab);
            }});

            setupFolderScroll();
            setTimeout(updateFolderArrows, 100);
        }}

        function selectFolder(folderId) {{
            activeFolderId = folderId;
            initFolders();
            filterChats();
        }}

        function getVisibleChats() {{
            const query = (document.getElementById("searchChats").value || "").toLowerCase().trim();
            return chatsData.filter(chat => {{
                // If user is searching, search globally across all chats (like Telegram)
                if (!query && activeFolderId !== "all") {{
                    if (!chat.folders || !Array.isArray(chat.folders)) return false;
                    const inFolder = chat.folders.some(fid => String(fid) === String(activeFolderId));
                    if (!inFolder) return false;
                }}
                // Search query filter: search in title, username, and message text/sender
                if (query) {{
                    const matchTitle = chat.title && chat.title.toLowerCase().includes(query);
                    const matchUser = chat.username && chat.username.toLowerCase().includes(query);
                    const matchMsg = chat.messages && chat.messages.some(m =>
                        (m.text && m.text.toLowerCase().includes(query)) ||
                        (m.sender && m.sender.toLowerCase().includes(query))
                    );
                    if (!matchTitle && !matchUser && !matchMsg) return false;
                }}
                return true;
            }});
        }}

        function filterChats() {{
            renderSidebar();
        }}

        function renderSidebar(customList = null) {{
            const list = document.getElementById("chatsList");
            list.innerHTML = "";
            const query = (document.getElementById("searchChats").value || "").trim();
            const chatsToRender = customList !== null ? customList : getVisibleChats();

            if (chatsToRender.length === 0) {{
                const msg = query ? "Ничего не найдено по запросу" : "В этой папке нет чатов за выбранный период";
                list.innerHTML = `<div style="padding: 24px 15px; color: #7f91a4; text-align: center; font-size: 13px;">${{msg}}</div>`;
                return;
            }}

            chatsToRender.forEach((chat) => {{
                const originalIndex = chatsData.indexOf(chat);
                const isSaved = chat.type === "saved";
                const item = document.createElement("div");
                item.className = "chat-item" + (originalIndex === activeChatIndex ? " active" : "") + (isSaved ? " saved" : "");
                item.onclick = () => selectChat(originalIndex);

                const avatarLetter = isSaved ? "📌" : (chat.title ? chat.title.trim().charAt(0).toUpperCase() : "?");
                const lastMsg = chat.messages && chat.messages.length > 0 ? chat.messages[chat.messages.length - 1].text || "[Медиа]" : "Нет сообщений";

                const photoCount = chat.messages ? chat.messages.filter(m => m.photo).length : 0;
                const photoBadge = photoCount > 0 ? `<span class="chat-photo-badge" title="${{photoCount}} фото">📷 ${{photoCount}}</span>` : "";

                item.innerHTML = `
                    <div class="avatar">${{avatarLetter}}</div>
                    <div class="chat-info">
                        <div class="chat-name-row">
                            <span class="chat-name">${{escapeHtml(chat.title || "Диалог")}}</span>
                            <div class="chat-badges">
                                ${{photoBadge}}
                                <span class="chat-count">${{chat.messages ? chat.messages.length : 0}}</span>
                            </div>
                        </div>
                        <div class="chat-preview">${{escapeHtml(lastMsg)}}</div>
                    </div>
                `;
                list.appendChild(item);
            }});
        }}

        function selectChat(index) {{
            activeChatIndex = index;
            renderSidebar();
            renderActiveChat();
        }}

        function renderActiveChat() {{
            const chat = chatsData[activeChatIndex];
            if (!chat) return;

            const photoCount = chat.messages ? chat.messages.filter(m => m.photo).length : 0;
            const voiceCount = chat.messages ? chat.messages.filter(m => m.voice).length : 0;
            const circleCount = chat.messages ? chat.messages.filter(m => m.circle).length : 0;

            const subParts = [
                chat.type_label || "Чат",
                chat.username ? "@" + chat.username : "ID: " + chat.id,
                `${{chat.messages ? chat.messages.length : 0}} сообщ.`
            ];
            if (photoCount > 0) subParts.push(`📷 ${{photoCount}} фото`);
            if (voiceCount > 0) subParts.push(`🎙 ${{voiceCount}} голос.`);
            if (circleCount > 0) subParts.push(`📹 ${{circleCount}} кружк.`);

            document.getElementById("chatHeader").style.display = "flex";
            document.getElementById("activeChatName").textContent = chat.title || "Диалог";
            document.getElementById("activeChatSub").textContent = subParts.join(" • ");

            const scrollContainer = document.getElementById("messagesScroll");
            scrollContainer.innerHTML = "";

            if (!chat.messages || chat.messages.length === 0) {{
                scrollContainer.innerHTML = '<div class="empty-state">В этом чате нет сообщений за выбранный период</div>';
                return;
            }}

            chat.messages.forEach(msg => {{
                const bubble = document.createElement("div");
                bubble.className = "msg-bubble " + (msg.out ? "out" : "in");

                let mediaHtml = "";
                if (msg.photo) {{
                    mediaHtml += `<div class="msg-photo-wrap"><img src="${{escapeHtml(msg.photo)}}" onclick="window.open(this.src)" alt="Фото"></div>`;
                }}
                if (msg.voice) {{
                    const vSrc = escapeHtml(msg.voice);
                    const isMp3 = vSrc.toLowerCase().endsWith('.mp3');
                    const primaryType = isMp3 ? 'audio/mpeg' : 'audio/ogg; codecs=opus';
                    mediaHtml += `
                    <div class="msg-voice-wrap">
                        <audio controls preload="metadata">
                            <source src="${{vSrc}}" type="${{primaryType}}">
                            <source src="${{vSrc}}">
                        </audio>
                        <a href="${{vSrc}}" download class="media-dl-btn" title="Скачать аудио">⬇️</a>
                    </div>`;
                }}
                if (msg.circle) {{
                    mediaHtml += `
                    <div class="msg-circle-wrap">
                        <video controls playsinline loop preload="metadata" onerror="this.closest('.msg-circle-wrap').innerHTML='<div style=\\'display:flex;height:100%;align-items:center;justify-content:center;text-align:center;padding:10px;color:#ff8080;font-size:11px;\\'>⚠️ Видео оборвано при сбросе сессии</div>'">
                            <source src="${{escapeHtml(msg.circle)}}" type="video/mp4">
                        </video>
                    </div>`;
                }}

                let textHtml = "";
                if (msg.text) {{
                    textHtml = `<div class="msg-text">${{escapeHtml(msg.text)}}</div>`;
                }} else if (!mediaHtml) {{
                    textHtml = `<div class="msg-text msg-placeholder">📎 [Вложение / Медиа]</div>`;
                }}

                bubble.innerHTML = `
                    <div class="msg-sender">${{escapeHtml(msg.sender || (msg.out ? "Вы" : "Собеседник"))}}</div>
                    ${{textHtml}}
                    ${{mediaHtml}}
                    <div class="msg-meta">${{escapeHtml(msg.date || "")}}</div>
                `;
                scrollContainer.appendChild(bubble);
            }});

            // Scroll to bottom
            scrollContainer.scrollTop = scrollContainer.scrollHeight;
        }}

        function escapeHtml(text) {{
            if (!text) return "";
            return String(text)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }}

        // Init
        initFolders();
        if (chatsData.length > 0) {{
            selectChat(0);
        }} else {{
            renderSidebar();
        }}
    </script>
</body>
</html>
"""
