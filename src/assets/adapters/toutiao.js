/* 头条号 · 图文发布页适配
 * 页面：https://mp.toutiao.com/profile_v4/graphic/publish
 */
(function () {
  var SEL = {
    title: [
      'textarea[placeholder*="标题"]',
      'input[placeholder*="标题"]',
      '.title-input textarea',
      '.byte-input__textarea'
    ],
    editor: [
      '.ProseMirror',
      '.ql-editor',
      'div[contenteditable="true"].ProseMirror',
      'div[contenteditable="true"]'
    ],
    fileInput: ['input[type="file"]'],
    submit: ['button[class*="publish"]', 'button[class*="primary"]'],
    login: ['.login-wrap', '.qrcode-container', '[class*="login"] canvas']
  };
  var SUBMIT_TEXT = ['预览并发布', '发布', '发表'];

  function findEditor() {
    var list = DF.many(SEL.editor);
    for (var i = 0; i < list.length; i++) {
      if (DF.visible(list[i])) return list[i];
    }
    return null;
  }

  window.DragonFlow = {
    name: '头条号',

    ready: function () {
      if (DF.one(SEL.login)) return false;
      return !!findEditor() || !!DF.one(SEL.title);
    },

    fill: function (payload) {
      payload = payload || {};
      var filled = [], missing = [];

      if (DF.one(SEL.login)) {
        return DF.result(false, [], [], '未登录，请先扫码登录头条号后台');
      }

      if (payload.title) {
        var t = DF.one(SEL.title);
        if (t) { DF.setValue(t, String(payload.title).slice(0, 30)); filled.push('title'); }
        else { missing.push('title'); }
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
          if (topics && topics.length) filled.push('topics');
        }
      } else {
        missing.push('body');
      }

      var ok = filled.length > 0;
      return DF.result(ok, filled, missing,
        ok ? (missing.length ? '已填充，需人工补：' + missing.join('、') : '填充完成')
           : '没有找到编辑区域，可能页面结构已变化');
    },

    submit: function () {
      if (DF.one(SEL.login)) return DF.result(false, [], [], '未登录，无法发布');
      var btn = DF.byText(SUBMIT_TEXT, 'button') || DF.one(SEL.submit);
      if (!btn) return DF.result(false, [], [], '没有找到发布按钮，请手动点击');
      if (btn.disabled) return DF.result(false, [], [], '发布按钮不可点，请检查内容是否完整');
      btn.click();
      return DF.result(true, ['submit'], [], '已触发发布，请在页面上确认结果');
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
        submitBtn: !!DF.one(SEL.submit),
        contentEditables: DF.many(['[contenteditable="true"]']).length,
        inputs: DF.many(['input']).length
      };
    }
  };
})();
