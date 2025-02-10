const API_BASE = "/api";

// --------------------
// 公共接口函数
// --------------------

// 获取市场时间及状态
async function fetchTimeStatus() {
  const res = await fetch(`${API_BASE}/time_status`);
  if (!res.ok) throw new Error("API /time_status error");
  return res.json();
}

// 获取最近休假日信息
async function fetchHolidays() {
  const res = await fetch(`${API_BASE}/recent_holidays`);
  if (!res.ok) throw new Error("API /recent_holidays error");
  return res.json();
}

// 获取指定股票行情数据
async function fetchQuote(symbol) {
  const res = await fetch(`${API_BASE}/quote?symbol=${symbol}`);
  if (!res.ok) throw new Error("API /quote error");
  return res.json();
}

// 将秒数格式化为 HH:mm:ss
function formatSeconds(seconds) {
  if (seconds < 0) return "0s";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

// --------------------
// 市场信息更新
// --------------------
function updateMarketInfo() {
  fetchTimeStatus()
    .then(data => {
      document.getElementById("usTime").innerText = data.us_time;
      document.getElementById("chinaTime").innerText = data.china_time;
      
      const currentStateElem = document.getElementById("currentState");
      currentStateElem.innerText = data.current_state;
      
      // 根据不同状态添加不同的样式
      currentStateElem.className = 'market-status ' + 
        (data.current_state === '盘中' ? 'status-trading' :
         data.current_state === '盘前' ? 'status-pre' :
         data.current_state === '盘后' ? 'status-post' : 'status-closed');
      
      document.getElementById("nextState").innerText = data.next_state;
      
      let secondsLeft = data.time_to_next_state_seconds;
      const countdownElem = document.getElementById("countdown");
      if (window.countdownInterval) clearInterval(window.countdownInterval);
      window.countdownInterval = setInterval(() => {
        if (secondsLeft <= 0) {
          clearInterval(window.countdownInterval);
          countdownElem.innerText = "即将刷新...";
          updateMarketInfo();
          return;
        }
        countdownElem.innerText = formatSeconds(secondsLeft);
        secondsLeft--;
      }, 1000);
    })
    .catch(err => console.error(err));
}

function updateHolidays() {
  fetchHolidays()
    .then(data => {
      const list = document.getElementById("holidaysList");
      list.innerHTML = "";
      if (data.upcoming_holiday) {
        const li = document.createElement("li");
        li.className = "list-group-item";
        li.innerText = `${data.upcoming_holiday.eventName} (${data.upcoming_holiday.atDate})`;
        list.appendChild(li);
      } else {
        const li = document.createElement("li");
        li.className = "list-group-item";
        li.innerText = "暂无休假日信息";
        list.appendChild(li);
      }
    })
    .catch(err => console.error(err));
}

// --------------------
// 自选股票 Watchlist 功能
// --------------------

// 从 localStorage 获取 watchlist 数组
function getWatchlist() {
    const list = localStorage.getItem("watchlist");
    return list ? JSON.parse(list) : [];
}

// 将 watchlist 保存到 localStorage
function setWatchlist(list) {
    localStorage.setItem("watchlist", JSON.stringify(list));
}

// 渲染自选股票列表
function renderWatchlist() {
    const watchlistContainer = document.getElementById("watchlist");
    const watchlist = getWatchlist();
    watchlistContainer.innerHTML = "";
    watchlist.forEach(symbol => {
        const col = document.createElement("div");
        col.className = "col-12 col-md-4 my-2";
        const card = document.createElement("div");
        card.className = "card p-2";
        card.setAttribute("data-symbol", symbol);
        
        const title = document.createElement("h5");
        title.innerText = symbol.toUpperCase();
        
        const priceP = document.createElement("p");
        priceP.innerHTML = `当前价格: <span class="price">--</span>`;
        
        const changeP = document.createElement("p");
        changeP.innerHTML = `涨跌幅: <span class="change">--</span>`;
        
        const deleteBtn = document.createElement("button");
        deleteBtn.className = "btn btn-sm btn-danger";
        deleteBtn.innerText = "删除";
        deleteBtn.addEventListener("click", () => {
            removeStock(symbol);
        });
        
        card.appendChild(title);
        card.appendChild(priceP);
        card.appendChild(changeP);
        card.appendChild(deleteBtn);
        col.appendChild(card);
        watchlistContainer.appendChild(col);
    });
}

// 更新自选股票行情数据
async function updateWatchlistData() {
    const watchlist = getWatchlist();
    watchlist.forEach(async (symbol) => {
        try {
            const data = await fetchQuote(symbol);
            const card = document.querySelector(`[data-symbol="${symbol}"]`);
            if (card) {
                const priceElem = card.querySelector(".price");
                const changeElem = card.querySelector(".change");
                if (data.current_price != null && data.previous_close != null) {
                    priceElem.innerText = parseFloat(data.current_price).toFixed(2);
                    const change = data.change;
                    const percent = data.percent_change;
                    let sign = change >= 0 ? "+" : "";
                    changeElem.innerText = `${sign}${change} (${sign}${percent}%)`;
                    changeElem.style.color = change >= 0 ? "green" : "red";
                } else {
                    priceElem.innerText = "--";
                    changeElem.innerText = "--";
                }
            }
        } catch (err) {
            console.error("Error updating watchlist data for", symbol, err);
        }
    });
}

function addStock(symbol) {
    symbol = symbol.trim().toUpperCase();
    if (!symbol) return;
    let watchlist = getWatchlist();
    if (!watchlist.includes(symbol)) {
        watchlist.push(symbol);
        setWatchlist(watchlist);
        renderWatchlist();
        updateWatchlistData();
    }
}

function removeStock(symbol) {
    let watchlist = getWatchlist();
    watchlist = watchlist.filter(s => s !== symbol);
    setWatchlist(watchlist);
    renderWatchlist();
}

// 监听添加按钮点击事件
document.getElementById("addStockBtn").addEventListener("click", () => {
    const symbol = prompt("请输入股票代码（例如 AAPL）：");
    if (symbol) {
        addStock(symbol);
    }
});

// --------------------
// 初始化与定时更新
// --------------------
function init() {
  updateMarketInfo();
  updateHolidays();
  renderWatchlist();
  updateWatchlistData();
  setInterval(updateMarketInfo, 60000);
  setInterval(updateHolidays, 300000);
  setInterval(updateWatchlistData, 60000);
}

document.addEventListener("DOMContentLoaded", init);
