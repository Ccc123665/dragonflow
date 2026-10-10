/* 公众号 · 图文素材编辑器适配
 * 页面：https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isNew=1&type=10
 *
 * ⚠️ 特殊规则：公众号「发布」即群发，一天只有一次且不可撤回。
 *    本适配器 **不做自动提交**，submit() 只负责尝试保存草稿，
 *    最终群发必须由人工到后台确认。
 *    另外公众号正文编辑器为 iframe（ueditor / ProseMirror），
 *    脚本会自动下钻到 iframe 内查找。
 */
(function () {
  var SEL = {
    title: [
      '#title',
      'textarea#title',
      'input#title',
      'textarea[placeholder*="标题"]'
    ],
    digest: ['textarea#js_description', 'textarea[placeholder*="摘要"]'],
    editorInIframe: ['#ueditor_0', 'body.view', '.ProseMirror', 'div[contenteditable="true"]'],
    saveDraft: ['#js_save', 'button#js_save'],
    login: ['#login_container', '.login__type__container', '.qrcode']
  };
  var SAVE_TEXT = ['保存为草稿', '保存'];

  /* 递归在 iframe 里找编辑器 */
  function findEditor() {
    var top = DF.many(SEL.editorInIframe);
    for (var i = 0; i < top.length; i++) {
      if (DF.visible(top[i])) return top[i];
    }
    var iframes = document.querySelectorAll('iframe');
    for (var j = 0; j < iframes.length; j++) {
      try {
        var doc = iframes[j].contentDocument;
        if (!doc) continue;
        var inner = doc.querySelectorAll(
          '.ProseMirror, body.view, div[contenteditable="true"], #ueditor_0'
        );
        for (var k = 0; k < inner.length; k++) {
          if (inner[k]) return inner[k];
        }
      } catch (e) { /* 跨域 iframe，跳过 */ }
    }
    return null;
  }

  window.DragonFlow = {
    name: '公众号',

    ready: function () {
      if (DF.one(SEL.login)) return false;
      return !!DF.one(SEL.title) || !!findEditor();
    },

    fill: function (payload) {
      payload = payload || {};
      var filled = [], missing = [];

      if (DF.one(SEL.login)) {
        return DF.result(false, [], [], '未登录，请先扫码登录公众号后台');
      }

      if (payload.title) {
        var t = DF.one(SEL.title);
        if (t) { DF.setValue(t, String(payload.title).slice(0, 64)); filled.push('title'); }
        else { missing.push('title'); }
      }

      if (payload.digest) {
        var d = DF.one(SEL.digest);
        if (d) { DF.setValue(d, String(payload.digest).slice(0, 120)); filled.push('digest'); }
      }

      var editor = findEditor();
      if (editor) {
        var body = payload.body || '';
        var topics = payload.topics;
        if (topics && topics.length) {
          var tagText = topics.map(function (x) {
            return '#' + String(x).replace(/^#/, '').trim();
          }).join(' ');
          body = (body ? body + '\n\n' : '') + tagText;
        }
        if (body) {
          DF.typeRich(editor, body);
          filled.push('body');
        }
      } else {
        missing.push('body');
      }

      /* 公众号排版建议由人工在编辑器内微调 */
      if (payload.body) missing.push('排版');

      var ok = filled.indexOf('body') >= 0 || filled.indexOf('title') >= 0;
      return DF.result(ok, filled, missing,
        ok ? '已填充。公众号正文排版建议人工微调后再保存草稿'
           : '没有找到正文编辑器，可能页面结构已变化');
    },

    /* 只保存草稿，绝不触发群发 */
    submit: function () {
      if (DF.one(SEL.login)) return DF.result(false, [], [], '未登录，无法保存');
      var btn = DF.one(SEL.saveDraft) || DF.byText(SAVE_TEXT, 'button');
      if (!btn) {
        return DF.result(false, [], [], '没有找到「保存为草稿」按钮，请手动保存。群发请人工确认');
      }
      btn.click();
      return DF.result(true, ['draft'], [],
        '已保存为草稿。公众号群发一天仅一次且不可撤回，请人工到后台确认后手动群发');
    },

    /* 诊断：登录态自动标记（workbench._probe_login）只认这里的 login 字段。 */
    diagnose: function () {
      return {
        url: location.href,
        host: location.host,
        login: !!DF.one(SEL.login),
        title: !!DF.one(SEL.title),
        editor: !!findEditor(),
        fileInput: !!DF.one(SEL.fileInput),
        saveBtn: !!DF.one(SEL.saveDraft),
        contentEditables: DF.many(['[contenteditable="true"]']).length,
        inputs: DF.many(['input']).length
      };
    }
  };
})();
