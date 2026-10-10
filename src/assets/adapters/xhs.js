/* 小红书 · 创作服务平台发布页适配
 * 页面：https://creator.xiaohongshu.com/publish/publish?from=menu_left&target=image
 *
 * ⚠️ 平台改版时只需改本文件的选择器，不必重新打包主程序。
 *
 * 2026-09 重写。之前「一键填充」一直报「没有找到正文编辑器」，四个坑：
 *   1. 图文 / 视频是**两个不同的 URL**（target=image / target=video），不是同一页的
 *      两个 tab。发布页默认落在 target=video，那一页**压根没有正文编辑器**。
 *      → 发布页地址已在 platforms.json 里直接指到 target=image。
 *   2. 标题框有个 4px 宽的隐藏替身（和真框同 class）。不带可见性过滤取第一个，
 *      会填进那个假的，Vue 的 v-model 不 commit，标题永远是空的。
 *      → 所有取值都带 offsetWidth 下限过滤。
 *   3. 正文编辑器现在不一定是 .ql-editor，更常见的是带 placeholder="描述" 的
 *      contenteditable。→ 选择器按优先级铺开，兜底用宽泛的 [contenteditable]。
 *   4. 传图 / 切页后表单是**异步**渲染的，而 Qt 的 runJavaScript **不 await
 *      Promise**（实测 Promise.resolve(...) 直接变成 {}），脚本没法自己 sleep。
 *      → 只能返回 retry:true，由发布队列延迟重跑同一项（publisher.py 的 PublishQueue）。
 *      重试期间用 window 上的状态位保证「切 tab / 点上传」各只做一次，不会重复触发。
 */
(function () {
  var SEL = {
    /* 标题输入框 */
    title: [
      'input[placeholder*="请输入标题"]',
      'input[placeholder*="标题"]',
      'input[maxlength="20"]',
      '[contenteditable="true"][placeholder*="标题"]'
    ],
    /* 正文富文本编辑器 */
    editor: [
      '[contenteditable="true"][placeholder*="描述"]',
      '[contenteditable="true"][class*="content"]',
      '.ql-editor',
      '.content-input div[contenteditable="true"]',
      'div[contenteditable="true"]',
      '[contenteditable="true"]'
    ],
    /* 图文 / 视频 切换（新页面按 URL 走，这里只作兜底） */
    tabImage: ['#tab-image', '.creator-tab:nth-child(1)'],
    tabVideo: ['#tab-video', '.creator-tab:nth-child(2)'],
    /* 上传控件 */
    fileInput: ['input[type="file"][accept*="image"]', 'input[type="file"]'],
    /* 发布按钮是 closed shadow DOM 的 web component，host.click() 无效 */
    publishHost: ['xhs-publish-btn', 'xhs-publish-button'],
    submit: ['button.d-button.primary', 'button[class*="publish"]', 'button[class*="submit"]'],
    /* 未登录提示 */
    login: ['.login-container', '[class*="login-box"]', '.qrcode-img']
  };

  var SUBMIT_TEXT = ['发布', '发布笔记'];
  var IMAGE_TAB_TEXT = ['上传图文', '上传笔记', '图文'];
  /* 找不到 input[type=file] 时，按这些文本点「唤起上传」的按钮 */
  var UPLOAD_TEXT = ['上传图片', '上传图文', '上传笔记', '点击上传', '选择图片'];
  /* closed shadow DOM 里能调到的实例方法名，逐个试 */
  var PUBLISH_METHODS = ['_onPublish', 'onPublish', '_onSubmit', '_handlePublish'];

  var TITLE_MIN_W = 50;    // 隐藏替身只有 4px 宽，卡在 50 就能滤掉
  var EDITOR_MIN_W = 80;

  /* 重试期间的状态位。挂在 window 上是为了跨 runJavaScript 调用存活
     （每次注入都是一个新的函数作用域，闭包变量活不过一次调用）。 */
  function state() {
    if (!window.__DF_XHS_STATE__) {
      window.__DF_XHS_STATE__ = { tabTried: false, uploadTried: false };
    }
    return window.__DF_XHS_STATE__;
  }

  /* 取值策略：先要「可见 + 够宽」的；一个都没有就退而取**最宽**的那个。
     为什么不是直接返回 null：窗口很窄时所有候选都会低于宽度阈值，
     那时放弃会让「填充」在正常页面上无谓地失败。取最宽的那个仍然躲得开
     4px 的隐藏替身（替身永远是最窄的）。 */
  function pick(selectors, minWidth, exclude, skip) {
    var list = DF.many(selectors);
    var visible = [];
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      if (exclude && el === exclude) continue;
      if (skip && skip(el)) continue;
      if (!DF.visible(el)) continue;
      visible.push(el);
    }
    if (!visible.length) return null;

    for (var j = 0; j < visible.length; j++) {
      if (!minWidth || visible[j].offsetWidth >= minWidth) return visible[j];
    }
    var best = visible[0];
    for (var k = 1; k < visible.length; k++) {
      if (visible[k].offsetWidth > best.offsetWidth) best = visible[k];
    }
    return best;
  }

  function placeholderOf(el) {
    return String((el && el.getAttribute && el.getAttribute('placeholder')) || '');
  }

  function findTitle() {
    return pick(SEL.title, TITLE_MIN_W, null, null);
  }

  /* 正文编辑器。排除标题框 —— 标题在某些版本里也是 contenteditable，
     不排掉就会把标题当正文写，正文那栏永远空着。 */
  function findEditor(exclude) {
    return pick(SEL.editor, EDITOR_MIN_W, exclude || null, function (el) {
      return placeholderOf(el).indexOf('标题') >= 0;
    });
  }

  function norm(s) {
    return String(s == null ? '' : s).replace(/\s+/g, '');
  }

  /* 写 + 回读校验。
     小红书是 Vue 受控组件，值没 commit 的话读回来是空的 ——
     与其让用户以为填上了，不如当场报出来。 */
  function writeField(el, value, isRich) {
    if (isRich) {
      DF.typeRich(el, value);
    } else {
      DF.setValue(el, value);
    }
    return norm(DF.editorText(el)).length > 0;
  }

  window.DragonFlow = {
    name: '小红书',

    ready: function () {
      if (DF.one(SEL.login)) return false;
      return !!findEditor(findTitle()) || !!DF.one(SEL.fileInput);
    },

    /* 同步填充：标题 + 正文 + 话题文本
     * 话题以「#话题 」纯文本写入，小红书编辑器会自动识别为话题标签。
     */
    fill: function (payload) {
      payload = payload || {};
      var filled = [];
      var missing = [];

      if (DF.one(SEL.login)) {
        return DF.result(false, [], [], '未登录，请先在该账号的浏览器里扫码登录');
      }

      var ST = state();
      var titleEl = findTitle();
      var editor = findEditor(titleEl);
      /* 这个平台要不要「先传素材」。
         以前这里读的是「有没有文件可传」（_upload_count > 0），于是内容里没有配图时
         **压根不点上传** —— 而图文页是先上传图片才渲染出标题 / 正文编辑框的，
         结果永远停在「没有找到正文编辑器」。现在由宿主告诉脚本「这个平台要先传」，
         与有没有文件可传无关。 */
      var wantUpload = !!payload._want_upload;
      var fileCount = Number(payload._upload_count || 0);

      /* ---------- 1) 编辑器还没出现 → 先试着切到「上传图文」（只切一次） ---------- */
      if (!editor && !ST.tabTried) {
        ST.tabTried = true;
        var tab = DF.clickTab(IMAGE_TAB_TEXT, 60);
        if (!tab) {
          var legacy = DF.one(SEL.tabImage);
          if (legacy && DF.visible(legacy)) {
            DF.clickEl(legacy);
            tab = legacy;
          }
        }
        if (tab) {
          return DF.result(false, [], [], '正在切到「上传图文」页…',
                           { retry: true, stage: 'switch' });
        }
      }

      /* ---------- 2) 需要先传素材 → 点一次上传（只点一次） ----------
         宿主已经把文件路径预置好了（browser.py 的 chooseFiles 会交回去），
         所以点下去不会弹系统对话框，浏览器直接当成用户选了文件。
         状态位挂在 window 上，跨重试存活 —— 同一页面只点一次，不重复传图。
         想重传：点浏览器工具条的「刷新」，页面重载后状态位会重置。 */
      if (wantUpload && !ST.uploadTried && !editor) {
        var trig = DF.findUploadTrigger(UPLOAD_TEXT);
        if (trig) {
          ST.uploadTried = true;
          try { trig.click(); } catch (e) { /* 忽略 */ }
          if (fileCount > 0) {
            return DF.result(false, [], [],
                             '正在上传 ' + fileCount + ' 个配图，等页面就绪…',
                             { retry: true, stage: 'upload' });
          }
          /* 没有配图可传：宿主没预置文件，点下去会弹系统对话框 ——
             这是**故意**的。让用户自己选一张图，编辑框就会出现，
             然后再点一次「一键填充」就能填进去。 */
          return DF.result(false, [], [],
            '图文页要先上传图片，才会出现标题 / 正文编辑框。'
            + '已帮你点开上传，选好图片、编辑框出现后 —— 再点一次「一键填充」即可',
            { manual: true, stage: 'need-upload' });
        }
      }

      /* 传完图页面会重渲染，编辑器可能刚出现，重新找一次 */
      if (!editor) {
        editor = findEditor(titleEl);
        titleEl = findTitle();
      }

      /* ---------- 3) 还是没有编辑器 → 等待或报错 ---------- */
      if (!editor) {
        /* 要传素材，但页面上连上传入口都没找到 —— 别再重试了，交人工 */
        if (wantUpload && !ST.uploadTried) {
          return DF.result(false, [], [],
            '页面上没找到上传入口（上传按钮 / 文件选择框）。'
            + '请确认停在小红书「上传图文」页，或手动点一下页面上的「上传图片」',
            { manual: true, stage: 'no-upload-trigger' });
        }
        if (ST.tabTried || ST.uploadTried) {
          return DF.result(false, [], [], '页面还在渲染，等一会儿…',
                           { retry: true, stage: 'wait' });
        }
        return DF.result(false, [], [],
          '没找到正文编辑器。请确认地址栏是 creator.xiaohongshu.com/publish/publish'
          + '（图文页 URL 应带 target=image）、且该账号已登录');
      }

      /* ---------- 标题 ---------- */
      if (payload.title) {
        if (titleEl) {
          var t = String(payload.title).slice(0, 20);
          if (writeField(titleEl, t, false)) filled.push('title');
          else missing.push('title');
        } else {
          missing.push('title');
        }
      }

      /* ---------- 正文 + 话题 ---------- */
      var body = payload.body || '';
      var topics = payload.topics;
      if (topics && topics.length) {
        var tagText = topics.map(function (t) {
          return '#' + String(t).replace(/^#/, '').trim();
        }).join(' ');
        body = (body ? body + '\n\n' : '') + tagText;
      }
      if (body) {
        if (writeField(editor, body, true)) {
          filled.push('body');
          if (topics && topics.length) filled.push('topics');
        } else {
          missing.push('body');
        }
      }

      /* ---------- 平台无对应字段，交人工 ---------- */
      if (payload.cover) missing.push('cover');
      if (payload.image_hint) missing.push('image_hint');

      var ok = filled.indexOf('body') >= 0;
      var msg;
      if (ok) {
        msg = missing.length ? '已填充，需人工补：' + missing.join('、') : '填充完成';
      } else if (filled.length) {
        msg = '只填上了 ' + filled.join('、') + '，正文没写进去 —— '
            + '编辑器可能不接收脚本输入，请手动粘贴正文';
      } else {
        msg = '没有找到正文编辑器，可能页面结构已变化';
      }
      return DF.result(ok, filled, missing, msg);
    },

    /* 提交：小红书发布按钮是 <xhs-publish-btn>，背后是 **closed** shadow root，
     * host 级 .click() 不会派发进内部 handler，必须直接调实例方法。
     */
    submit: function () {
      if (DF.one(SEL.login)) {
        return DF.result(false, [], [], '未登录，无法发布');
      }

      var hosts = DF.many(SEL.publishHost);
      for (var i = 0; i < hosts.length; i++) {
        if (!DF.visible(hosts[i])) continue;
        for (var j = 0; j < PUBLISH_METHODS.length; j++) {
          var name = PUBLISH_METHODS[j];
          try {
            if (typeof hosts[i][name] === 'function') {
              hosts[i][name]();
              return DF.result(true, ['submit'], [],
                '已触发发布（实例方法 ' + name + '），请在页面上确认结果');
            }
          } catch (e) { /* 换下一个方法名试 */ }
        }
      }

      /* 兜底：按可见文本点 button / [role=button] */
      var btn = DF.one(SEL.submit) || DF.byText(SUBMIT_TEXT, 'button,[role="button"]');
      if (!btn) {
        return DF.result(false, [], [],
          '没有找到发布按钮（页面可能改版了），请手动点击');
      }
      if (btn.disabled || btn.getAttribute('aria-disabled') === 'true') {
        return DF.result(false, [], [], '发布按钮不可点，请检查内容是否完整');
      }
      DF.clickEl(btn);
      return DF.result(true, ['submit'], [], '已触发发布，请在页面上确认结果');
    },

    /* 诊断：把页面上到底有什么报回来，供界面上的「诊断」按钮显示。
     * 写这个是因为「填不上」的可能原因太多，靠猜不如直接看。 */
    diagnose: function () {
      var ST = state();
      return {
        url: location.href,
        host: location.host,
        login: !!DF.one(SEL.login),
        title: !!findTitle(),
        editor: !!findEditor(findTitle()),
        fileInput: !!DF.one(SEL.fileInput),
        uploadTrigger: !!DF.findUploadTrigger(UPLOAD_TEXT),
        hasMedia: DF.hasUploadedMedia(),
        imageTab: !!DF.findTab(IMAGE_TAB_TEXT, 60),
        publishHost: DF.many(SEL.publishHost).length,
        submitBtn: !!DF.one(SEL.submit),
        contentEditables: DF.many(['[contenteditable="true"]']).length,
        inputs: DF.many(['input']).length,
        tried: {tab: ST.tabTried, upload: ST.uploadTried}
      };
    }
  };
})();
