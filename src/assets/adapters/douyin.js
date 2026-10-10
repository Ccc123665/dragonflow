/* 抖音 · 创作者中心发布页适配
 * 页面：https://creator.douyin.com/creator-micro/content/upload
 * 抖音以视频为主，图文为次；本适配器负责标题、简介、话题的填充。
 */
(function () {
  var SEL = {
    title: [
      'input[placeholder*="标题"]',
      'input[placeholder*="填写作品标题"]',
      '.semi-input',
      '.title-input input'
    ],
    editor: [
      '.zone-container',
      'div[contenteditable="true"].editor-kit-container',
      'div[contenteditable="true"]'
    ],
    fileInput: ['input[type="file"]'],
    submit: ['button[class*="primary"]', 'button[class*="publish"]'],
    login: ['.login-scan-container', '[class*="login"] canvas', '.qrcode']
  };
  var SUBMIT_TEXT = ['发布', '立即发布'];

  function findEditor() {
    var list = DF.many(SEL.editor);
    for (var i = 0; i < list.length; i++) {
      if (DF.visible(list[i])) return list[i];
    }
    return null;
  }

  window.DragonFlow = {
    name: '抖音',

    ready: function () {
      if (DF.one(SEL.login)) return false;
      return !!findEditor();
    },

    fill: function (payload) {
      payload = payload || {};
      var filled = [], missing = [];

      if (DF.one(SEL.login)) {
        return DF.result(false, [], [], '未登录，请先在该账号的浏览器里扫码登录');
      }

      if (payload.title) {
        var t = DF.one(SEL.title);
        if (t) { DF.setValue(t, String(payload.title).slice(0, 30)); filled.push('title'); }
        else { missing.push('title'); }
      }

      var editor = findEditor();
      if (editor) {
        var parts = [];
        if (payload.hook) parts.push(String(payload.hook));
        if (payload.body) parts.push(String(payload.body));
        if (payload.cta) parts.push(String(payload.cta));
        var body = parts.join('\n\n');
        var topics = payload.topics;
        if (topics && topics.length) {
          body += '\n\n' + topics.map(function (x) {
            return '#' + String(x).replace(/^#/, '').trim();
          }).join(' ');
        }
        if (body) {
          DF.typeRich(editor, body);
          filled.push('body');
          if (topics && topics.length) filled.push('topics');
        }
      } else {
        missing.push('body');
      }

      if (payload.shot_hint) missing.push('shot_hint');
      if (payload.video_path) missing.push('video');

      var ok = filled.indexOf('body') >= 0 || filled.indexOf('title') >= 0;
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

    /* 诊断：把页面上到底有什么报回来 —— 「诊断当前页」按钮和登录态
     * 自动标记（workbench._probe_login 只认这里的 login 字段）都靠它。
     * ⚠ 缺了 diagnose，账号登录了也会永远挂着「未登录」。 */
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
