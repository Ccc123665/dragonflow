/* DragonFlow 适配脚本公共库
 * 所有平台适配脚本都会被自动前置注入本文件，可直接使用下列工具函数。
 * 只使用标准 DOM API，不依赖任何前端框架。
 */
(function () {
  if (window.__DF_COMMON__) return;
  window.__DF_COMMON__ = true;

  var DF = {
    /* ---------- 查询 ---------- */
    one: function (selectors, root) {
      var list = Array.isArray(selectors) ? selectors : [selectors];
      for (var i = 0; i < list.length; i++) {
        try {
          var el = (root || document).querySelector(list[i]);
          if (el) return el;
        } catch (e) { /* 选择器非法，跳过 */ }
      }
      return null;
    },

    many: function (selectors, root) {
      var out = [];
      var list = Array.isArray(selectors) ? selectors : [selectors];
      for (var i = 0; i < list.length; i++) {
        try {
          var found = (root || document).querySelectorAll(list[i]);
          if (found && found.length) out = out.concat(Array.prototype.slice.call(found));
        } catch (e) { /* 跳过 */ }
      }
      return out;
    },

    /* 按可见文本找元素（用于找按钮） */
    byText: function (texts, tag) {
      var list = Array.isArray(texts) ? texts : [texts];
      var nodes = document.querySelectorAll(tag || 'button,div,span,a');
      for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        var t = (el.innerText || el.textContent || '').trim();
        if (!t) continue;
        for (var j = 0; j < list.length; j++) {
          if (t === list[j]) {
            if (el.offsetParent !== null) return el;
          }
        }
      }
      return null;
    },

    visible: function (el) {
      if (!el) return false;
      if (el.offsetParent === null) return false;
      var r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    },

    /* ---------- 点击 ----------
       很多发布页的 tab / 按钮是 <div> 或 <span> 挂了 onClick，
       直接 el.click() 在 React 里是能触发的（React 不校验 isTrusted），
       但个别页面监听的是 mousedown，所以补一套鼠标事件序列兜底。 */
    clickEl: function (el) {
      if (!el) return false;
      try {
        el.scrollIntoView({ block: 'center' });
      } catch (e) { /* 忽略 */ }
      try {
        ['mousedown', 'mouseup', 'click'].forEach(function (t) {
          el.dispatchEvent(new MouseEvent(t, {
            bubbles: true, cancelable: true, view: window
          }));
        });
        return true;
      } catch (e) {
        try { el.click(); return true; } catch (e2) { return false; }
      }
    },

    /* ---------- 按文本找「标签页 / 按钮」 ----------
       为什么不能只靠 CSS 选择器：小红书这类平台改版很勤，
       `#tab-image` / `.creator-tab:nth-child(1)` 说没就没，而「上传图文」
       这四个字反而稳定。取**最深**的命中元素 —— 文本在 span 里、onClick
       挂在父 div 上时，点 span 的 click 会冒泡上去，两种结构都能命中。 */
    findTab: function (labels, maxHeight) {
      var list = Array.isArray(labels) ? labels : [labels];
      var nodes = document.querySelectorAll('div,span,a,li,button');
      var best = null, bestDepth = -1;
      var cap = maxHeight || 90;
      for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        var t = (el.innerText || el.textContent || '').trim();
        if (!t || list.indexOf(t) < 0) continue;
        if (!DF.visible(el)) continue;
        if (el.getBoundingClientRect().height > cap) continue;   // 排除整块容器
        var d = 0, p = el;
        while (p) { d++; p = p.parentElement; }
        if (d > bestDepth) { bestDepth = d; best = el; }
      }
      return best;
    },

    clickTab: function (labels, maxHeight) {
      var el = DF.findTab(labels, maxHeight);
      if (!el) return null;
      DF.clickEl(el);
      return el;
    },

    /* ---------- 编辑器是否已经有内容 ---------- */
    editorText: function (el) {
      if (!el) return '';
      if (typeof el.value === 'string') return el.value;
      return (el.innerText || el.textContent || '');
    },

    sleep: function (ms) {
      return new Promise(function (r) { setTimeout(r, ms); });
    },

    /* ---------- 赋值：兼容 React / Vue 受控组件 ----------
       React 会在元素实例上定义自己的 value 存取器，直接用 el.value = x
       不会触发它的 onChange。这里改为取「原型上的原生 setter」赋值，
       绕过实例上的存取器，React 就会判定值变了并触发 onChange。 */
    setValue: function (el, value) {
      if (!el) return false;
      var v = String(value);
      var ok = false;
      try {
        var proto = Object.getPrototypeOf(el);
        var desc = proto ? Object.getOwnPropertyDescriptor(proto, 'value') : null;
        if (desc && desc.set) {
          desc.set.call(el, v);
          ok = true;
        }
      } catch (e) { ok = false; }
      if (!ok) {
        try { el.value = v; } catch (e) { /* 忽略 */ }
      }
      try { el.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) { /* 忽略 */ }
      try { el.dispatchEvent(new Event('change', { bubbles: true })); } catch (e) { /* 忽略 */ }
      return true;
    },

    /* ---------- 富文本注入：让编辑器当成用户输入 ---------- */
    typeRich: function (el, text) {
      if (!el || !text) return false;
      el.focus();
      try {
        var sel = window.getSelection();
        sel.removeAllRanges();
        var range = document.createRange();
        range.selectNodeContents(el);
        range.collapse(false);
        sel.addRange(range);
      } catch (e) { /* 忽略 */ }

      var ok = false;
      try {
        ok = document.execCommand('insertText', false, text);
      } catch (e) { ok = false; }

      if (!ok) {
        try {
          var dt = new DataTransfer();
          dt.setData('text/plain', text);
          el.dispatchEvent(new InputEvent('beforeinput', {
            bubbles: true, cancelable: true, inputType: 'insertText', data: text
          }));
          el.dispatchEvent(new InputEvent('input', {
            bubbles: true, inputType: 'insertText', data: text
          }));
          el.dispatchEvent(new ClipboardEvent('paste', {
            bubbles: true, cancelable: true, clipboardData: dt
          }));
        } catch (e) { /* 忽略 */ }
      }

      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.dispatchEvent(new Event('blur', { bubbles: true }));
      return true;
    },

    /* 逐段输入：按换行切成多段，规避部分编辑器对超长插入的截断 */
    typeRichLines: function (el, text) {
      if (!el || !text) return false;
      var lines = String(text).split('\n');
      el.focus();
      for (var i = 0; i < lines.length; i++) {
        if (i > 0) {
          try { document.execCommand('insertLineBreak', false, null); } catch (e) { /* 忽略 */ }
          try { document.execCommand('insertParagraph', false, null); } catch (e) { /* 忽略 */ }
        }
        if (lines[i]) {
          try { document.execCommand('insertText', false, lines[i]); } catch (e) { /* 忽略 */ }
        }
      }
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    },

    /* ---------- 话题标签：输入 # 后回车选中下拉项 ---------- */
    async addTopics(editor, topics) {
      if (!editor || !topics || !topics.length) return 0;
      var done = 0;
      for (var i = 0; i < topics.length; i++) {
        var t = String(topics[i]).replace(/^#/, '').trim();
        if (!t) continue;
        editor.focus();
        try {
          document.execCommand('insertText', false, '\n#' + t);
        } catch (e) { continue; }
        await DF.sleep(700);
        var pick = DF.one([
          '.publish-topic-list .item',
          '[class*="topic"] li',
          '[class*="suggest"] li',
          '.dropdown-item'
        ]);
        if (pick && DF.visible(pick)) {
          pick.click();
          done++;
          await DF.sleep(250);
        } else {
          /* 下拉没出来：退化为纯文本标签 */
          try { document.execCommand('insertText', false, ' '); } catch (e) { /* 忽略 */ }
        }
      }
      return done;
    },

    /* ---------- 文件上传：触发 input[type=file] ---------- */
    setFiles(input, paths) {
      if (!input || !paths || !paths.length) return false;
      /* 页面脚本无法构造真实 File 对象，此处只能做「点击唤起 + 交给宿主拦截」 */
      input.click();
      return true;
    },

    /* ---------- 找「能唤起文件选择」的元素 ----------
       为什么不能只认 input[type=file]：发布页上有几种常见形态 ——
         · 隐藏的 input，靠 label / 按钮代理点击
         · 点「上传图片」按钮时才动态插入 input
         · 一个 input 同时挂着视频 / 封面 / 头像，必须挑对
       所以：先找 input（点它最干净，Qt 会直接拦 chooseFiles，不弹系统对话框），
       找不到再按文本点按钮。input 通常 display:none，**不能过滤可见性**。 */
    findUploadTrigger: function (labels) {
      var inputs = DF.many([
        'input[type="file"][accept*="image"]',
        'input[type="file"][accept*="video"]',
        'input[type="file"]'
      ]);
      for (var i = 0; i < inputs.length; i++) {
        if (!inputs[i].disabled) return inputs[i];
      }
      var list = Array.isArray(labels) ? labels : [labels];
      var nodes = document.querySelectorAll('button,div,span,a,label');
      for (var j = 0; j < nodes.length; j++) {
        var el = nodes[j];
        var t = (el.innerText || el.textContent || '').trim();
        if (!t || list.indexOf(t) < 0) continue;
        if (!DF.visible(el)) continue;
        if (el.getBoundingClientRect().height > 80) continue;   // 排除整块容器
        return el;
      }
      return null;
    },

    /* 页面上有没有「已经传好的素材」（缩略图 / 预览图）。
       图文页的编辑框往往在图片上传完成之后才渲染 —— 用它判断"图到位了没"。 */
    hasUploadedMedia: function () {
      var sel = [
        '.img-container img', '[class*="preview"] img', '[class*="upload"] img',
        '[class*="material"] img', 'img[src^="blob:"]', 'img[src^="http"]'
      ];
      var found = DF.many(sel);
      for (var i = 0; i < found.length; i++) {
        var r = found[i].getBoundingClientRect();
        if (r.width >= 40 && r.height >= 40) return true;
      }
      return false;
    },

    /* ---------- 结果 ----------
       extra.retry = true 表示「这一步没成，但不是错，请稍后重跑同一项」。
       用于「点了 tab，编辑器还没渲染出来」这类异步等待 ——
       Qt 的 runJavaScript **不会 await Promise**，脚本没法自己 sleep，
       只能把这个信号交回 Python 侧，由发布队列延迟重试。 */
    result(ok, filled, missing, message, extra) {
      var r = {
        ok: !!ok,
        filled: filled || [],
        missing: missing || [],
        message: message || (ok ? '完成' : '失败'),
        url: location.href
      };
      if (extra) {
        for (var k in extra) {
          if (Object.prototype.hasOwnProperty.call(extra, k)) r[k] = extra[k];
        }
      }
      return r;
    }
  };

  window.DF = DF;
})();
