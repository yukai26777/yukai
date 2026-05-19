/**
 * StockPOC – main.js
 * jQuery 事件流程：
 *   1. DOM Ready → 初始化日期、載入策略清單
 *   2. #fetchBtn click → fetchData()
 *   3. #backtestBtn click → runBacktest()
 */
$(function () {
  /* ── 初始化預設日期（近一年）────────────────────────── */
  (function initDates() {
    const today = new Date();
    const oneYearAgo = new Date(today);
    oneYearAgo.setFullYear(today.getFullYear() - 1);
    const fmt = (d) => d.toISOString().slice(0, 10);
    $("#endDate").val(fmt(today));
    $("#startDate").val(fmt(oneYearAgo));
  })();

  /* ── 載入策略清單（驗證 API 連線）──────────────────── */
  $.get("/api/strategies")
    .done(function (res) {
      if (!res.success) return;
      // POC 只有一個策略，直接顯示即可（無需動態渲染選單）
    })
    .fail(function () {
      showAlert("#fetchAlert", "⚠️ 無法連線至後端 API，請確認伺服器是否啟動", "error");
    });

  /* ══════════════════════════════════════════════════════════
   * 取得資料
   * ══════════════════════════════════════════════════════ */
  $("#fetchBtn").on("click", function () {
    const symbol    = $("#symbolInput").val().trim();
    const startDate = $("#startDate").val();
    const endDate   = $("#endDate").val();

    /* 前端簡易驗證 */
    if (!symbol) {
      return showAlert("#fetchAlert", "請輸入股票代碼", "error");
    }
    if (!startDate || !endDate) {
      return showAlert("#fetchAlert", "請選擇開始與結束日期", "error");
    }
    if (startDate >= endDate) {
      return showAlert("#fetchAlert", "開始日期必須早於結束日期", "error");
    }

    setBtnLoading("#fetchBtn", true);
    hideAlert("#fetchAlert");

    $.ajax({
      url: "/api/fetch_data",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({ symbol, start_date: startDate, end_date: endDate }),
    })
      .done(function (res) {
        if (!res.success) {
          return showAlert("#fetchAlert", "❌ " + res.error, "error");
        }
        showAlert("#fetchAlert", `✅ 成功取得 ${res.symbol} 的資料（${res.candlestick.length} 筆）`, "success");
        renderIndicators(res.indicators);
        renderCandleChart(res);
        /* 顯示策略區塊 */
        showSection("#strategySection");
        /* 隱藏上次回測結果 */
        $("#backtestSection").addClass("d-none");
      })
      .fail(function () {
        showAlert("#fetchAlert", "❌ 網路錯誤，請稍後再試", "error");
      })
      .always(function () {
        setBtnLoading("#fetchBtn", false);
      });
  });

  /* ══════════════════════════════════════════════════════════
   * 執行回測
   * ══════════════════════════════════════════════════════ */
  $("#backtestBtn").on("click", function () {
    const symbol      = $("#symbolInput").val().trim();
    const startDate   = $("#startDate").val();
    const endDate     = $("#endDate").val();
    const shortWindow = parseInt($("#shortWindow").val(), 10);
    const longWindow  = parseInt($("#longWindow").val(), 10);

    if (!symbol || !startDate || !endDate) {
      return showAlert("#backtestAlert", "請先取得資料後再執行回測", "error");
    }
    if (isNaN(shortWindow) || isNaN(longWindow)) {
      return showAlert("#backtestAlert", "視窗值必須為整數", "error");
    }
    if (shortWindow >= longWindow) {
      return showAlert("#backtestAlert", "短期視窗必須小於長期視窗", "error");
    }

    setBtnLoading("#backtestBtn", true);
    hideAlert("#backtestAlert");

    $.ajax({
      url: "/api/backtest",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({
        symbol,
        start_date: startDate,
        end_date: endDate,
        strategy: "ma",
        params: { short_window: shortWindow, long_window: longWindow },
      }),
    })
      .done(function (res) {
        if (!res.success) {
          return showAlert("#backtestAlert", "❌ " + res.error, "error");
        }
        renderBacktestResult(res);
        showSection("#backtestSection");
      })
      .fail(function () {
        showAlert("#backtestAlert", "❌ 網路錯誤，請稍後再試", "error");
      })
      .always(function () {
        setBtnLoading("#backtestBtn", false);
      });
  });

  /* ══════════════════════════════════════════════════════════
   * 渲染函式
   * ══════════════════════════════════════════════════════ */

  /** 更新指標卡片 */
  function renderIndicators(ind) {
    $("#mPrice").text(fmtNum(ind.current_price));
    $("#mMA20").text(ind.ma20 !== null ? fmtNum(ind.ma20) : "N/A");
    $("#mMA50").text(ind.ma50 !== null ? fmtNum(ind.ma50) : "N/A");

    const rsiEl = $("#mRSI");
    if (ind.rsi !== null) {
      rsiEl.text(ind.rsi.toFixed(1));
      rsiEl.removeClass("positive negative warn");
      if (ind.rsi >= 70) rsiEl.addClass("warn");
      else if (ind.rsi <= 30) rsiEl.addClass("positive");
    } else {
      rsiEl.text("N/A");
    }

    $("#mVolume").text(fmtVolume(ind.volume));
    showSection("#indicatorsSection");
  }

  /** K 線 + MA 圖 */
  function renderCandleChart(res) {
    const candles = res.candlestick;
    const dates   = candles.map((d) => d.date);

    const traceCandle = {
      type: "candlestick",
      name: res.symbol,
      x: dates,
      open:  candles.map((d) => d.open),
      high:  candles.map((d) => d.high),
      low:   candles.map((d) => d.low),
      close: candles.map((d) => d.close),
      increasing: { line: { color: "#6bcb77" } },
      decreasing: { line: { color: "#ff6b6b" } },
    };

    const traceMA20 = {
      type: "scatter",
      mode: "lines",
      name: "MA20",
      x: res.ma20.map((d) => d.date),
      y: res.ma20.map((d) => d.value),
      line: { color: "#4facfe", width: 1.5 },
    };

    const traceMA50 = {
      type: "scatter",
      mode: "lines",
      name: "MA50",
      x: res.ma50.map((d) => d.date),
      y: res.ma50.map((d) => d.value),
      line: { color: "#f093fb", width: 1.5 },
    };

    const layout = plotlyLayout(`${res.symbol} K 線圖`);
    layout.xaxis.rangeslider = { visible: false };

    Plotly.react("candleChart", [traceCandle, traceMA20, traceMA50], layout, plotlyConfig());
    showSection("#chartSection");
  }

  /** 回測績效 */
  function renderBacktestResult(res) {
    const m = res.metrics;

    setMetric("#rTotalReturn", m.total_return, "%", true);
    setMetric("#rAnnualReturn", m.annual_return, "%", true);

    const sharpeEl = $("#rSharpe");
    sharpeEl.text(m.sharpe_ratio.toFixed(2));
    sharpeEl.removeClass("positive negative warn");
    if (m.sharpe_ratio >= 1) sharpeEl.addClass("positive");
    else if (m.sharpe_ratio < 0) sharpeEl.addClass("negative");

    const ddEl = $("#rMaxDD");
    ddEl.text(m.max_drawdown.toFixed(2) + "%");
    ddEl.removeClass("positive negative");
    ddEl.addClass("negative");

    setMetric("#rWinRate", m.win_rate, "%", true);
    $("#rTradeCount").text(m.trade_count);

    /* 權益曲線 */
    const eq = res.equity_curve;
    const traceEq = {
      type: "scatter",
      mode: "lines",
      fill: "tozeroy",
      name: "權益曲線",
      x: eq.map((d) => d.date),
      y: eq.map((d) => d.equity),
      line: { color: "#00d4aa", width: 2 },
      fillcolor: "rgba(0,212,170,0.08)",
    };

    const shortWin = $("#shortWindow").val();
    const longWin  = $("#longWindow").val();
    const layout = plotlyLayout(`MA(${shortWin}/${longWin}) 策略權益曲線`);
    layout.yaxis.tickformat = ".3f";

    Plotly.react("equityChart", [traceEq], layout, plotlyConfig());
  }

  /* ══════════════════════════════════════════════════════════
   * 工具函式
   * ══════════════════════════════════════════════════════ */

  function setBtnLoading(selector, loading) {
    const btn = $(selector);
    btn.prop("disabled", loading);
    btn.find(".btn-text").toggleClass("d-none", loading);
    btn.find(".btn-loading").toggleClass("d-none", !loading);
  }

  function showAlert(selector, msg, type) {
    const el = $(selector);
    el.removeClass("d-none error success").addClass(type).html(msg);
  }

  function hideAlert(selector) {
    $(selector).addClass("d-none").text("");
  }

  function showSection(selector) {
    const el = $(selector);
    el.removeClass("d-none").addClass("fade-in");
    // 移除動畫 class，讓下次還能觸發
    setTimeout(() => el.removeClass("fade-in"), 500);
  }

  function fmtNum(v) {
    if (v === null || v === undefined) return "N/A";
    return parseFloat(v).toLocaleString("zh-Hant", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    });
  }

  function fmtVolume(v) {
    if (v >= 1e8) return (v / 1e8).toFixed(2) + "億";
    if (v >= 1e4) return (v / 1e4).toFixed(1) + "萬";
    return v.toLocaleString();
  }

  function setMetric(selector, value, suffix, colorize) {
    const el = $(selector);
    el.text(value.toFixed(2) + suffix);
    if (colorize) {
      el.removeClass("positive negative");
      if (value > 0) el.addClass("positive");
      else if (value < 0) el.addClass("negative");
    }
  }

  /** Plotly 通用佈局 */
  function plotlyLayout(title) {
    return {
      title: { text: title, font: { color: "#e8eaf0", size: 14 } },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "#6b7280", family: "Space Mono, monospace", size: 11 },
      margin: { t: 40, r: 20, b: 40, l: 60 },
      legend: {
        bgcolor: "rgba(0,0,0,0)",
        font: { color: "#e8eaf0" },
      },
      xaxis: {
        gridcolor: "rgba(255,255,255,0.05)",
        linecolor: "rgba(255,255,255,0.1)",
        tickfont: { color: "#6b7280" },
      },
      yaxis: {
        gridcolor: "rgba(255,255,255,0.05)",
        linecolor: "rgba(255,255,255,0.1)",
        tickfont: { color: "#6b7280" },
      },
      hoverlabel: {
        bgcolor: "#0f1525",
        bordercolor: "#00d4aa",
        font: { color: "#e8eaf0" },
      },
    };
  }

  function plotlyConfig() {
    return {
      responsive: true,
      displayModeBar: true,
      modeBarButtonsToRemove: ["autoScale2d", "lasso2d", "select2d"],
      displaylogo: false,
    };
  }
});
