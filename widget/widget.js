/**
 * MEDPLATFORM AI Chatbot Widget v1.0.0
 * Usage: <script src="https://chatbot.medplatform.io/static/widget.js"
 *                 data-clinic-id="YOUR_CLINIC_ID" async></script>
 */
(function () {
  'use strict';

  // --- Config ---
  const script = document.currentScript ||
    document.querySelector('script[data-clinic-id]');
  if (!script) return;

  const CLINIC_ID = script.getAttribute('data-clinic-id');
  const API_BASE = script.getAttribute('data-api-url') ||
    'http://localhost:8005';

  if (!CLINIC_ID) {
    console.warn('[MEDPLATFORM] data-clinic-id is required');
    return;
  }

  // --- State ---
  let sessionId = null;
  let config = null;
  let isOpen = false;
  let isLoading = false;
  let leadCaptured = false;

  // --- Init ---
  async function init() {
    try {
      const res = await fetch(`${API_BASE}/api/chat/session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          clinic_id: CLINIC_ID,
          source_url: window.location.href,
          source_surface: 'widget',
          visitor_id: getVisitorId(),
        }),
      });

      if (!res.ok) {
        console.warn('[MEDPLATFORM] Chatbot not available for this clinic');
        return;
      }

      const data = await res.json();
      sessionId = data.session_id;
      config = data.config;

      injectStyles(
        data.primary_color || '#007AE6',
        data.config?.widget_position || 'bottom-right'
      );

      buildWidget(
        data.bot_name || 'Assistant',
        data.welcome_message,
        data.primary_color || '#007AE6'
      );

      setTimeout(showLauncher, 2000);
    } catch (e) {
      console.warn('[MEDPLATFORM] Widget init failed:', e.message);
    }
  }

  // --- DOM Building ---
  function buildWidget(botName, welcomeMessage, primaryColor) {
    const container = document.createElement('div');
    container.id = 'mp-chatbot';
    container.innerHTML = `
      <button id="mp-launcher" aria-label="Open chat">
        <svg id="mp-launcher-icon" width="24" height="24" viewBox="0 0 24 24" fill="none">
          <path d="M20 2H4C2.9 2 2 2.9 2 4V22L6 18H20C21.1 18 22 17.1 22 16V4C22 2.9 21.1 2 20 2Z" fill="white"/>
        </svg>
        <svg id="mp-close-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" style="display:none">
          <path d="M18 6L6 18M6 6L18 18" stroke="white" stroke-width="2" stroke-linecap="round"/>
        </svg>
        <span id="mp-unread-badge" style="display:none">1</span>
      </button>

      <div id="mp-window" style="display:none" role="dialog" aria-label="Chat with ${botName}">
        <div id="mp-header">
          <div id="mp-header-avatar">${botName[0].toUpperCase()}</div>
          <div>
            <div id="mp-header-name">${botName}</div>
            <div id="mp-header-status">\u25CF Online</div>
          </div>
          <button id="mp-minimize" aria-label="Minimize chat">\u2212</button>
        </div>

        <div id="mp-messages" role="log" aria-live="polite"></div>

        <div id="mp-lead-form" style="display:none">
          <p id="mp-lead-form-title">Leave your details and we\u2019ll follow up:</p>
          <input id="mp-input-name" type="text" placeholder="Your name" autocomplete="name"/>
          <input id="mp-input-email" type="email" placeholder="Email address" autocomplete="email"/>
          <input id="mp-input-phone" type="tel" placeholder="Phone (optional)" autocomplete="tel"/>
          <button id="mp-lead-submit">Send \u2192</button>
        </div>

        <div id="mp-actions" style="display:none"></div>

        <div id="mp-input-area">
          <textarea id="mp-input" placeholder="Type a message\u2026" rows="1" aria-label="Type your message"></textarea>
          <button id="mp-send" aria-label="Send message">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M22 2L11 13M22 2L15 22L11 13M22 2L2 9L11 13" stroke="white" stroke-width="2" stroke-linecap="round"/>
            </svg>
          </button>
        </div>

        <div id="mp-footer">Powered by <strong>MEDPLATFORM</strong></div>
      </div>
    `;
    document.body.appendChild(container);

    addMessage('assistant', welcomeMessage);

    document.getElementById('mp-launcher').onclick = toggleChat;
    document.getElementById('mp-minimize').onclick = toggleChat;
    document.getElementById('mp-send').onclick = handleSend;
    document.getElementById('mp-lead-submit').onclick = handleLeadSubmit;

    var input = document.getElementById('mp-input');
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    });
    input.addEventListener('input', function () {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });
  }

  // --- Chat functions ---
  function toggleChat() {
    isOpen = !isOpen;
    var win = document.getElementById('mp-window');
    var launchIcon = document.getElementById('mp-launcher-icon');
    var closeIcon = document.getElementById('mp-close-icon');
    var badge = document.getElementById('mp-unread-badge');

    win.style.display = isOpen ? 'flex' : 'none';
    launchIcon.style.display = isOpen ? 'none' : 'block';
    closeIcon.style.display = isOpen ? 'block' : 'none';
    badge.style.display = 'none';

    if (isOpen) {
      document.getElementById('mp-input').focus();
      scrollToBottom();
    }
  }

  function showLauncher() {
    var launcher = document.getElementById('mp-launcher');
    if (launcher) {
      launcher.style.opacity = '1';
      launcher.style.transform = 'scale(1)';
      document.getElementById('mp-unread-badge').style.display = 'flex';
    }
  }

  async function handleSend() {
    var input = document.getElementById('mp-input');
    var content = input.value.trim();
    if (!content || isLoading || !sessionId) return;

    input.value = '';
    input.style.height = 'auto';
    addMessage('user', content);
    showTypingIndicator();
    isLoading = true;

    var actionsEl = document.getElementById('mp-actions');
    actionsEl.style.display = 'none';
    actionsEl.innerHTML = '';

    try {
      var res = await fetch(
        `${API_BASE}/api/chat/session/${sessionId}/message`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: content, visitor_id: getVisitorId() }),
        }
      );

      removeTypingIndicator();

      if (!res.ok) throw new Error('Request failed');
      var data = await res.json();

      addMessage('assistant', data.reply);

      if (data.suggested_actions && data.suggested_actions.length > 0) {
        renderActions(data.suggested_actions);
      }

      if (!leadCaptured && data.qualification_score >= 30 && !data.lead_captured) {
        showLeadForm();
      }

      if (data.lead_captured) {
        leadCaptured = true;
        hideLeadForm();
      }
    } catch (e) {
      removeTypingIndicator();
      addMessage('assistant', 'Sorry, I had trouble connecting. Please try again.');
    } finally {
      isLoading = false;
    }
  }

  async function handleLeadSubmit() {
    var name = document.getElementById('mp-input-name').value.trim();
    var email = document.getElementById('mp-input-email').value.trim();
    var phone = document.getElementById('mp-input-phone').value.trim();

    if (!email || !email.includes('@')) {
      document.getElementById('mp-input-email').style.borderColor = '#ef4444';
      return;
    }

    try {
      await fetch(`${API_BASE}/api/chat/session/${sessionId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, email: email, phone: phone }),
      });
      hideLeadForm();
      leadCaptured = true;
      addMessage('assistant',
        "Thanks! We\u2019ll be in touch soon. Is there anything else I can help you with?");
    } catch (e) {
      addMessage('assistant', 'Sorry, there was an issue. Please try again.');
    }
  }

  // --- DOM helpers ---
  function addMessage(role, content) {
    var messages = document.getElementById('mp-messages');
    var div = document.createElement('div');
    div.className = 'mp-msg mp-msg-' + role;
    div.innerHTML = content.replace(/\n/g, '<br>');
    messages.appendChild(div);
    scrollToBottom();
  }

  function showTypingIndicator() {
    var messages = document.getElementById('mp-messages');
    var div = document.createElement('div');
    div.className = 'mp-msg mp-msg-assistant mp-typing';
    div.id = 'mp-typing';
    div.innerHTML = '<span></span><span></span><span></span>';
    messages.appendChild(div);
    scrollToBottom();
  }

  function removeTypingIndicator() {
    var el = document.getElementById('mp-typing');
    if (el) el.remove();
  }

  function renderActions(actions) {
    var el = document.getElementById('mp-actions');
    el.innerHTML = '';
    actions.forEach(function (action) {
      var btn = document.createElement('a');
      btn.className = 'mp-action-btn';
      btn.textContent = action.label;
      if (action.url) {
        btn.href = action.url;
        btn.target = '_blank';
        btn.rel = 'noopener';
      }
      el.appendChild(btn);
    });
    el.style.display = 'flex';
  }

  function showLeadForm() {
    var form = document.getElementById('mp-lead-form');
    if (form && form.style.display === 'none') {
      form.style.display = 'block';
      scrollToBottom();
    }
  }

  function hideLeadForm() {
    var form = document.getElementById('mp-lead-form');
    if (form) form.style.display = 'none';
  }

  function scrollToBottom() {
    var messages = document.getElementById('mp-messages');
    if (messages) messages.scrollTop = messages.scrollHeight;
  }

  // --- Styles ---
  function injectStyles(primaryColor, position) {
    var isRight = position !== 'bottom-left';
    var posStyle = isRight ? 'right:20px;bottom:20px;' : 'left:20px;bottom:20px;';
    var windowPos = isRight ? 'right:20px;bottom:80px;' : 'left:20px;bottom:80px;';

    var css = [
      '#mp-chatbot *{box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;}',
      '#mp-launcher{position:fixed;' + posStyle + 'width:56px;height:56px;background:' + primaryColor + ';border-radius:50%;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 16px rgba(0,0,0,0.2);z-index:999998;opacity:0;transform:scale(0.8);transition:opacity 0.3s,transform 0.3s;}',
      '#mp-launcher:hover{transform:scale(1.08)!important;}',
      '#mp-unread-badge{position:absolute;top:-2px;right:-2px;width:18px;height:18px;background:#ef4444;border-radius:50%;color:white;font-size:11px;font-weight:700;align-items:center;justify-content:center;border:2px solid white;}',
      '#mp-window{position:fixed;' + windowPos + 'width:360px;height:520px;background:#fff;border-radius:16px;flex-direction:column;box-shadow:0 8px 40px rgba(0,0,0,0.18);z-index:999997;overflow:hidden;border:1px solid rgba(0,0,0,0.08);}',
      '#mp-header{background:' + primaryColor + ';padding:14px 16px;display:flex;align-items:center;gap:10px;flex-shrink:0;}',
      '#mp-header-avatar{width:36px;height:36px;background:rgba(255,255,255,0.25);border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;font-weight:700;font-size:15px;}',
      '#mp-header-name{color:white;font-weight:600;font-size:14px;}',
      '#mp-header-status{color:rgba(255,255,255,0.8);font-size:11px;}',
      '#mp-minimize{margin-left:auto;background:none;border:none;color:white;cursor:pointer;font-size:20px;line-height:1;padding:0 4px;opacity:0.8;}',
      '#mp-minimize:hover{opacity:1;}',
      '#mp-messages{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px;background:#f8fafc;}',
      '.mp-msg{max-width:80%;padding:10px 14px;border-radius:16px;font-size:14px;line-height:1.5;word-wrap:break-word;}',
      '.mp-msg-user{background:' + primaryColor + ';color:white;align-self:flex-end;border-bottom-right-radius:4px;}',
      '.mp-msg-assistant{background:white;color:#1f2937;align-self:flex-start;border-bottom-left-radius:4px;box-shadow:0 1px 4px rgba(0,0,0,0.08);}',
      '.mp-typing{display:flex;gap:5px;padding:12px 16px;}',
      '.mp-typing span{width:7px;height:7px;background:#94a3b8;border-radius:50%;animation:mp-bounce 1.2s infinite;}',
      '.mp-typing span:nth-child(2){animation-delay:0.2s;}',
      '.mp-typing span:nth-child(3){animation-delay:0.4s;}',
      '@keyframes mp-bounce{0%,80%,100%{transform:translateY(0);opacity:0.5;}40%{transform:translateY(-6px);opacity:1;}}',
      '#mp-actions{padding:6px 12px;gap:8px;flex-wrap:wrap;flex-shrink:0;}',
      '.mp-action-btn{background:' + primaryColor + '22;color:' + primaryColor + ';border:1px solid ' + primaryColor + '44;border-radius:20px;padding:6px 14px;font-size:13px;font-weight:500;cursor:pointer;text-decoration:none;white-space:nowrap;transition:background 0.2s;}',
      '.mp-action-btn:hover{background:' + primaryColor + '33;}',
      '#mp-lead-form{padding:12px 16px;background:#f0f9ff;border-top:1px solid #e0f2fe;flex-shrink:0;}',
      '#mp-lead-form-title{font-size:13px;color:#0369a1;margin:0 0 8px;font-weight:500;}',
      '#mp-lead-form input{width:100%;padding:8px 10px;border:1px solid #cbd5e1;border-radius:8px;font-size:13px;margin-bottom:6px;outline:none;background:white;}',
      '#mp-lead-form input:focus{border-color:' + primaryColor + ';}',
      '#mp-lead-submit{width:100%;padding:9px;background:' + primaryColor + ';color:white;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;}',
      '#mp-lead-submit:hover{opacity:0.9;}',
      '#mp-input-area{display:flex;gap:8px;padding:10px 12px;border-top:1px solid #f1f5f9;background:white;flex-shrink:0;align-items:flex-end;}',
      '#mp-input{flex:1;border:1px solid #e2e8f0;border-radius:20px;padding:9px 14px;font-size:14px;resize:none;outline:none;line-height:1.4;max-height:120px;overflow-y:auto;font-family:inherit;}',
      '#mp-input:focus{border-color:' + primaryColor + ';}',
      '#mp-send{width:38px;height:38px;background:' + primaryColor + ';border-radius:50%;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:opacity 0.2s;}',
      '#mp-send:hover{opacity:0.85;}',
      '#mp-footer{text-align:center;font-size:11px;color:#94a3b8;padding:6px;background:white;border-top:1px solid #f1f5f9;}',
      '@media(max-width:480px){#mp-window{width:100vw;height:100vh;bottom:0!important;right:0!important;left:0!important;border-radius:0;}#mp-launcher{' + posStyle + '}}',
    ].join('');

    var style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);
  }

  // --- Utils ---
  function getVisitorId() {
    var id = null;
    try { id = localStorage.getItem('mp_visitor_id'); } catch (e) {}
    if (!id) {
      id = 'v_' + Math.random().toString(36).slice(2, 11) + '_' + Date.now().toString(36);
      try { localStorage.setItem('mp_visitor_id', id); } catch (e) {}
    }
    return id;
  }

  // --- Boot ---
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
