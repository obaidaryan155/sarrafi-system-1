'use strict';

const api = {
    get: async (url) => {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    },
    post: async (url, data) => {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }
};

let loadingTimeout = null;
let toastTimeout = null;

function showToast(msg, ok = true) {
    const t = document.getElementById('toast');
    if (!t) return;
    t.textContent = msg;
    t.style.background = ok ? 'var(--primary)' : '#ef4444';
    t.style.display = 'block';
    if (toastTimeout) clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => t.style.display = 'none', 3500);
}

function showLoading(show) {
    const loader = document.getElementById('loadingScreen');
    if (!loader) return;
    if (show) {
        loader.style.display = 'flex';
        if (loadingTimeout) clearTimeout(loadingTimeout);
        loadingTimeout = setTimeout(() => {
            if (loader.style.display === 'flex') {
                loader.style.display = 'none';
                showToast('سیستم له وخت څخه زیات ونیو، مهرباني وکړئ صفحه تازه کړئ', false);
            }
        }, 10000);
    } else {
        loader.style.display = 'none';
        if (loadingTimeout) clearTimeout(loadingTimeout);
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>]/g, m => {
        if (m === '&') return '&amp;';
        if (m === '<') return '&lt;';
        if (m === '>') return '&gt;';
        return m;
    });
}

function formatDateShort(iso) {
    if (!iso) return '—';
    return iso.replace('T', ' ').substring(0, 19);
}

function showPage(pageId) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active-page'));
    const target = document.getElementById(pageId);
    if (target) target.classList.add('active-page');

    document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
    const activeBtn = document.getElementById(`btn-${pageId}`);
    if (activeBtn) activeBtn.classList.add('active');

    switch (pageId) {
        case 'dashboard': loadDashboard(); break;
        case 'exchange': loadExchangeHistory(); loadCurrencies(); break;
        case 'remittance': loadRemittances(); loadCurrencies(); break;
        case 'principal': loadPersonsBalances(); loadPrincipalHistory(); loadCurrencies(); break;
        case 'settings': loadRates(); loadCurrenciesForDelete(); break;
        case 'reports': loadReport(); break;
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function toggleTheme() {
    document.body.classList.toggle('dark-mode');
    const isDark = document.body.classList.contains('dark-mode');
    const themeBtn = document.querySelector('.theme-toggle-btn');
    if (themeBtn) {
        themeBtn.innerHTML = isDark ? '<span class="emoji-icon">☀️</span> <span>روښانه تیم</span>' : '<span class="emoji-icon">🌙</span> <span>تیاره تیم</span>';
    }
}

function updateDate() {
    const el = document.getElementById('currentDate');
    if (el) el.textContent = new Date().toLocaleDateString('fa-AF');
}

// ==================== Dashboard ====================
async function loadDashboard() {
    try {
        const data = await api.get('/api/get_dashboard_data');
        let cashHtml = '';
        for (const [curr, amt] of Object.entries(data.cash)) {
            cashHtml += `<div class="cash-card card-3d"><h3>${curr}</h3><h2>${Number(amt).toLocaleString()}</h2></div>`;
        }
        document.getElementById('cashCards').innerHTML = cashHtml;

        const exDiv = document.getElementById('todayExchanges');
        exDiv.innerHTML = data.today_exchanges.length
            ? data.today_exchanges.map(e => `<div>${e.given_amount} ${e.given_currency} → ${e.received_amount} ${e.received_currency}</div>`).join('')
            : '<div class="empty-list">نن تبادله نشته</div>';

        const remDiv = document.getElementById('todayRemittances');
        remDiv.innerHTML = data.today_remittances.length
            ? data.today_remittances.map(r => `<div>${r.sender_name} → ${r.receiver_name} : ${r.amount} ${r.currency} (${r.status})</div>`).join('')
            : '<div class="empty-list">نن حواله نشته</div>';

        let personsHtml = '<table><th>نوم</th><th>تذکره</th><th>خالص بیلانس</th><th>اسعار</th><th>عمل</th></tr>';
        data.persons.forEach(p => {
            personsHtml += `<tr>
                                <td>${escapeHtml(p.name)}</td>
                                <td>${escapeHtml(p.id_number)}</td>
                                <td class="${p.net >= 0 ? 'trust' : 'debt'}">${Number(p.net).toLocaleString()}</td>
                                <td>${p.currency}</td>
                                <td><button class="btn-sm" onclick="settlePerson(${p.id}, '${p.currency}')">وصل کول</button></td>
                            </tr>`;
        });
        personsHtml += '</table>';
        document.getElementById('personsSummary').innerHTML = personsHtml;
    } catch (err) {
        console.error(err);
        showToast('د ډشبورډ لوډولو کې ستونزه', false);
    }
}

// ==================== Currencies ====================
async function loadCurrencies() {
    try {
        const currencies = await api.get('/api/get_all_currencies');
        const selects = ['exGivenCurr', 'exReceivedCurr', 'remCurrency', 'principalCurrency'];
        selects.forEach(id => {
            const sel = document.getElementById(id);
            if (sel) {
                const oldVal = sel.value;
                sel.innerHTML = '';
                currencies.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c;
                    opt.textContent = c;
                    sel.appendChild(opt);
                });
                if (oldVal && currencies.includes(oldVal)) sel.value = oldVal;
                else if (id === 'exGivenCurr') sel.value = 'AFN';
                else if (id === 'exReceivedCurr') sel.value = 'USD';
            }
        });
    } catch (err) {
        console.error(err);
    }
}

async function loadCurrenciesForDelete() {
    try {
        const currencies = await api.get('/api/get_all_currencies');
        let html = '<table><th>اسعار</th><th>عمل</th></tr>';
        currencies.forEach(c => {
            html += `<tr><td>${c}</td><td><button class="btn-sm" onclick="deleteCurrency('${c}')">🗑️ ړنګول</button></td></tr>`;
        });
        html += '</table>';
        document.getElementById('currenciesList').innerHTML = html;
    } catch (err) {
        document.getElementById('currenciesList').innerHTML = '<div class="empty-list">شسي</div>';
    }
}

async function deleteCurrency(code) {
    if (!confirm(`آیا د اسعار ${code} ړنګولو ډاډ لرئ؟ ټول نرخونه به هم ړنګ شي.`)) return;
    try {
        const res = await api.post('/api/delete_currency', { currency: code });
        if (res.success) {
            showToast(res.message);
            loadCurrenciesForDelete();
            loadCurrencies();
            loadRates();
        } else {
            showToast(res.message, false);
        }
    } catch (err) {
        showToast('تېروتنه', false);
    }
}

function swapCurrencies() {
    const given = document.getElementById('exGivenCurr');
    const received = document.getElementById('exReceivedCurr');
    [given.value, received.value] = [received.value, given.value];
    liveCalc();
}

async function fetchRate() {
    const from = document.getElementById('exGivenCurr').value;
    const to = document.getElementById('exReceivedCurr').value;
    try {
        const res = await api.post('/api/get_exchange_rate', { from_curr: from, to_curr: to });
        if (res.rate) {
            document.getElementById('exRate').value = res.rate;
            liveCalc();
        } else {
            showToast('نرخ ونه موندل شو', false);
        }
    } catch (err) {
        showToast('د نرخ اخیستلو کې تېروتنه', false);
    }
}

function liveCalc() {
    const amount = parseFloat(document.getElementById('exGivenAmount').value);
    const rate = parseFloat(document.getElementById('exRate').value);
    const rec = document.getElementById('exReceivedAmount');
    if (!isNaN(amount) && !isNaN(rate)) {
        rec.value = (amount * rate).toFixed(2);
    } else {
        rec.value = '';
    }
}

async function saveExchange() {
    const data = {
        given_currency: document.getElementById('exGivenCurr').value,
        given_amount: parseFloat(document.getElementById('exGivenAmount').value),
        received_currency: document.getElementById('exReceivedCurr').value,
        received_amount: parseFloat(document.getElementById('exReceivedAmount').value),
        rate: parseFloat(document.getElementById('exRate').value),
        notes: document.getElementById('exNotes').value.trim()
    };
    if (isNaN(data.given_amount) || data.given_amount <= 0) {
        showToast('سم مقدار دننه کړئ', false);
        return;
    }
    try {
        const res = await api.post('/api/add_exchange_transaction', data);
        if (res.success) {
            showToast('تبادله ثبت شوه');
            document.getElementById('exGivenAmount').value = '';
            document.getElementById('exReceivedAmount').value = '';
            document.getElementById('exRate').value = '';
            document.getElementById('exNotes').value = '';
            loadDashboard();
            loadExchangeHistory();
        } else {
            showToast(res.message || 'تېروتنه', false);
        }
    } catch (err) {
        showToast('د تبادلې ثبتولو کې تېروتنه', false);
    }
}

async function loadExchangeHistory() {
    try {
        const rows = await api.get('/api/get_exchange_transactions');
        const container = document.getElementById('exchangeHistory');
        if (!rows.length) {
            container.innerHTML = '<div class="empty-list">تاریخ نشته</div>';
            return;
        }
        let html = '<div class="cards-grid">';
        rows.forEach(r => {
            html += `
                <div class="history-card">
                    <div class="card-header">
                        <span>🔄 تبادله #${r.id}</span>
                        <span>${formatDateShort(r.trans_date)}</span>
                    </div>
                    <div class="card-details">
                        <div>📤 ورکړه: ${r.given_amount} ${r.given_currency}</div>
                        <div>📥 ترلاسه: ${r.received_amount} ${r.received_currency}</div>
                        <div>💱 نرخ: ${r.rate}</div>
                        <div>📝 یادښت: ${escapeHtml(r.notes) || '—'}</div>
                    </div>
                    <div>
                        <button class="btn-sm" onclick="editExchange(${r.id})">✏️ سمول</button>
                        <button class="btn-sm" onclick="deleteExchange(${r.id})">🗑️ حذف</button>
                    </div>
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
    } catch (err) {
        document.getElementById('exchangeHistory').innerHTML = '<div class="empty-list">تاریخ نشته</div>';
    }
}

async function deleteExchange(id) {
    if (!confirm('آیا د دې تبادلې حذف کولو ډاډ لرئ؟')) return;
    try {
        const res = await api.post('/api/delete_exchange_transaction', { id });
        if (res.success) {
            showToast('حذف شو');
            loadDashboard();
            loadExchangeHistory();
        } else {
            showToast(res.message || 'تېروتنه', false);
        }
    } catch (err) {
        showToast('د حذفولو تېروتنه', false);
    }
}

async function editExchange(id) {
    // Simple prompt edit (could be modal)
    const rows = await api.get('/api/get_exchange_transactions');
    const tx = rows.find(r => r.id === id);
    if (!tx) return;
    const newGiven = prompt('نوې ورکړل شوې اندازه:', tx.given_amount);
    if (!newGiven) return;
    const newReceived = prompt('نوې ترلاسه شوې اندازه:', tx.received_amount);
    if (!newReceived) return;
    const newRate = prompt('نوی نرخ:', tx.rate);
    if (!newRate) return;
    try {
        const res = await api.post('/api/edit_exchange_transaction', {
            id: id,
            given_currency: tx.given_currency,
            given_amount: parseFloat(newGiven),
            received_currency: tx.received_currency,
            received_amount: parseFloat(newReceived),
            rate: parseFloat(newRate),
            notes: tx.notes
        });
        if (res.success) {
            showToast('معامله سمه شوه');
            loadDashboard();
            loadExchangeHistory();
        } else {
            showToast(res.message, false);
        }
    } catch (err) {
        showToast('تېروتنه', false);
    }
}

// ==================== Remittances ====================
async function addRemittance() {
    const data = {
        sender_name: document.getElementById('remSenderName').value.trim(),
        sender_id: document.getElementById('remSenderId').value.trim(),
        sender_phone: document.getElementById('remSenderPhone').value.trim(),
        sender_country: document.getElementById('remSenderCountry').value.trim(),
        receiver_name: document.getElementById('remReceiverName').value.trim(),
        receiver_country: document.getElementById('remReceiverCountry').value.trim(),
        amount: parseFloat(document.getElementById('remAmount').value),
        currency: document.getElementById('remCurrency').value,
        commission_percent: parseFloat(document.getElementById('remCommissionPercent').value) || 0,
        notes: document.getElementById('remNotes').value.trim()
    };
    if (!data.sender_name || !data.receiver_name || isNaN(data.amount) || data.amount <= 0) {
        showToast('نوم او مثبت مقدار اړین دی', false);
        return;
    }
    try {
        const res = await api.post('/api/add_remittance', data);
        if (res.success) {
            showToast(`حواله ثبت شوه. کوډ: ${res.reference} | کمیسیون: ${res.commission} ${data.currency}`);
            ['remSenderName', 'remSenderId', 'remSenderPhone', 'remSenderCountry',
             'remReceiverName', 'remReceiverCountry', 'remAmount', 'remNotes'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.value = '';
            });
            document.getElementById('remCommissionPercent').value = '10';
            loadRemittances();
            loadDashboard();
        } else {
            showToast(res.message || 'تېروتنه', false);
        }
    } catch (err) {
        showToast('د حوالې ثبتولو کې تېروتنه', false);
    }
}

async function loadRemittances() {
    try {
        const rows = await api.get('/api/get_remittances');
        let html = '<table><th>کوډ</th><th>لیږونکی</th><th>له هیواد</th><th>ترلاسه کوونکی</th><th>مقدار</th><th>کمیسیون</th><th>خالص</th><th>حالت</th><th>عمل</th></tr>';
        rows.forEach(r => {
            html += `<tr>
                        <td>${r.reference_number}</td>
                        <td>${escapeHtml(r.sender_name)}</td>
                        <td>${escapeHtml(r.sender_country || '—')}</td>
                        <td>${escapeHtml(r.receiver_name)}</td>
                        <td>${r.amount} ${r.currency}</td>
                        <td>${r.commission} ${r.currency}</td>
                        <td>${r.net_amount} ${r.currency}</td>
                        <td>${r.status}</td>
                        <td>
                            <button onclick="updateRemStatus('${r.reference_number}','completed')" class="btn-sm">✔️ بشپړ</button>
                            <button onclick="updateRemStatus('${r.reference_number}','failed')" class="btn-sm">❌ ناکام</button>
                            <button onclick="deleteRemittance('${r.reference_number}')" class="btn-sm">🗑️</button>
                        </td>
                    </tr>`;
        });
        html += '</table>';
        document.getElementById('remittancesList').innerHTML = html;
    } catch (err) {
        document.getElementById('remittancesList').innerHTML = '<div class="empty-list">د حوالو لیست نشته</div>';
    }
}

async function updateRemStatus(ref, status) {
    try {
        const res = await api.post('/api/update_remittance_status', { ref, status });
        if (res.success) {
            showToast('حالت بدل شو');
            loadRemittances();
            loadDashboard();
        } else {
            showToast(res.message || 'تېروتنه', false);
        }
    } catch (err) {
        showToast('د حالت بدلولو کې تېروتنه', false);
    }
}

async function deleteRemittance(ref) {
    if (!confirm('آیا د حوالې حذف کولو ډاډ لرئ؟')) return;
    try {
        const res = await api.post('/api/delete_remittance', { ref });
        if (res.success) {
            showToast('حواله حذف شوه');
            loadRemittances();
            loadDashboard();
        } else {
            showToast(res.message || 'تېروتنه', false);
        }
    } catch (err) {
        showToast('د حذفولو تېروتنه', false);
    }
}

// ==================== Principal (Connected Money) ====================
async function savePrincipalTransaction() {
    const data = {
        person_name: document.getElementById('principalPersonName').value.trim(),
        person_id_number: document.getElementById('principalPersonId').value.trim(),
        trans_type: document.getElementById('principalType').value,
        amount: parseFloat(document.getElementById('principalAmount').value),
        currency: document.getElementById('principalCurrency').value,
        notes: document.getElementById('principalNotes').value.trim()
    };
    if (!data.person_name || !data.person_id_number || isNaN(data.amount) || data.amount <= 0) {
        if (data.trans_type !== 'settlement') {
            showToast('نوم، تذکره او مثبت مقدار اړین دی', false);
            return;
        }
    }
    try {
        const res = await api.post('/api/add_principal_transaction', data);
        if (res.success) {
            showToast('معامله ثبت شوه');
            document.getElementById('principalPersonName').value = '';
            document.getElementById('principalPersonId').value = '';
            document.getElementById('principalAmount').value = '';
            document.getElementById('principalNotes').value = '';
            loadPersonsBalances();
            loadPrincipalHistory();
            loadDashboard();
        } else {
            showToast(res.message || 'تېروتنه', false);
        }
    } catch (err) {
        showToast('د معاملې ثبتولو کې تېروتنه', false);
    }
}

async function loadPersonsBalances() {
    try {
        const rows = await api.get('/api/get_all_person_balances');
        let html = '<table><th>نوم</th><th>تذکره</th><th>خالص بیلانس</th><th>اسعار</th><th>عمل</th></tr>';
        rows.forEach(p => {
            html += `<tr>
                        <td>${escapeHtml(p.name)}</td>
                        <td>${escapeHtml(p.id_number)}</td>
                        <td class="${p.net >= 0 ? 'trust' : 'debt'}">${Number(p.net).toLocaleString()}</td>
                        <td>${p.currency}</td>
                        <td><button class="btn-sm" onclick="settlePerson(${p.id}, '${p.currency}')">وصل کول</button></td>
                    </tr>`;
        });
        html += '</table>';
        document.getElementById('personsBalancesTable').innerHTML = html;
    } catch (err) {
        document.getElementById('personsBalancesTable').innerHTML = '<div class="empty-list">حسابونه نشته</div>';
    }
}

async function settlePerson(personId, currency) {
    if (!confirm('آیا د دې کس د پیسو وصل کولو ډاډ لرئ؟ بیلانس به صفر شي او پیسې به صندوق ته ور اضافه / کم شي.')) return;
    try {
        // Get person details
        const persons = await api.get('/api/get_all_person_balances');
        const person = persons.find(p => p.id === personId && p.currency === currency);
        if (!person) return;
        const amount = Math.abs(person.net);
        const transType = 'settlement';
        const res = await api.post('/api/add_principal_transaction', {
            person_name: person.name,
            person_id_number: person.id_number,
            trans_type: transType,
            amount: amount,
            currency: currency,
            notes: 'وصل کول (بندول)'
        });
        if (res.success) {
            showToast('پیسې وصل شوې، بیلانس صفر شو');
            loadPersonsBalances();
            loadPrincipalHistory();
            loadDashboard();
            loadReport();
        } else {
            showToast(res.message, false);
        }
    } catch (err) {
        showToast('تېروتنه', false);
    }
}

async function loadPrincipalHistory() {
    try {
        const rows = await api.get('/api/get_principal_transactions');
        const container = document.getElementById('principalHistory');
        if (!rows.length) {
            container.innerHTML = '<div class="empty-list">هیڅ معامله نشته</div>';
            return;
        }
        const typeMap = {
            'deposit': '💰 امانت ورکول',
            'withdrawal': '💸 امانت اخیستل',
            'loan_given': '📉 پور ورکول',
            'loan_received': '📈 پور اخیستل',
            'settlement': '🔗 وصل کول'
        };
        let html = '<div class="cards-grid">';
        rows.forEach(r => {
            let typeText = typeMap[r.trans_type] || r.trans_type;
            html += `
                <div class="history-card">
                    <div class="card-header">
                        <span>${typeText}</span>
                        <span>${formatDateShort(r.trans_date)}</span>
                    </div>
                    <div class="card-details">
                        <div>👤 ${escapeHtml(r.person_name)} (${escapeHtml(r.person_id_number)})</div>
                        <div>💰 ${Number(r.amount).toLocaleString()} ${r.currency}</div>
                        <div>📝 ${escapeHtml(r.notes) || '—'}</div>
                    </div>
                    <div>
                        <button class="btn-sm" onclick="editPrincipal(${r.id})">✏️ سمول</button>
                        <button class="btn-sm" onclick="deletePrincipalTransaction(${r.id})">🗑️ حذف</button>
                    </div>
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
    } catch (err) {
        document.getElementById('principalHistory').innerHTML = '<div class="empty-list">هیڅ معامله نشته</div>';
    }
}

async function editPrincipal(id) {
    const rows = await api.get('/api/get_principal_transactions');
    const tx = rows.find(r => r.id === id);
    if (!tx) return;
    const newAmount = prompt('نوې اندازه:', tx.amount);
    if (!newAmount) return;
    const newType = prompt('نوی ډول (deposit, withdrawal, loan_given, loan_received, settlement):', tx.trans_type);
    if (!newType) return;
    try {
        const res = await api.post('/api/edit_principal_transaction', {
            id: id,
            person_name: tx.person_name,
            person_id_number: tx.person_id_number,
            trans_type: newType,
            amount: parseFloat(newAmount),
            currency: tx.currency,
            notes: tx.notes
        });
        if (res.success) {
            showToast('معامله سمه شوه');
            loadPersonsBalances();
            loadPrincipalHistory();
            loadDashboard();
        } else {
            showToast(res.message, false);
        }
    } catch (err) {
        showToast('تېروتنه', false);
    }
}

async function deletePrincipalTransaction(id) {
    if (!confirm('آیا د معاملې حذف کولو ډاډ لرئ؟')) return;
    try {
        const res = await api.post('/api/delete_principal_transaction', { id });
        if (res.success) {
            showToast('معامله حذف شوه');
            loadPersonsBalances();
            loadPrincipalHistory();
            loadDashboard();
        } else {
            showToast(res.message || 'تېروتنه', false);
        }
    } catch (err) {
        showToast('د حذفولو تېروتنه', false);
    }
}

// ==================== Reports ====================
let reportChart = null;
async function loadReport() {
    showLoading(true);
    try {
        const data = await api.get('/api/get_report_data');
        const cardsDiv = document.getElementById('currencyReportCards');
        let cardsHtml = '';
        for (const [curr, amt] of Object.entries(data.cash)) {
            cardsHtml += `<div class="report-card"><h3>${curr}</h3><h2>${Number(amt).toLocaleString()}</h2><small>موجودي</small></div>`;
        }
        cardsDiv.innerHTML = cardsHtml || '<div class="empty-list">هیڅ اسعار نشته</div>';

        let personsHtml = '<tr><th>نوم</th><th>اسعار</th><th>خالص بیلانس</th></tr>';
        data.persons_net.forEach(p => {
            personsHtml += `<tr>
                                <td>${escapeHtml(p.name)}</td>
                                <td>${p.currency}</td>
                                <td class="${p.net >= 0 ? 'trust' : 'debt'}">${Number(p.net).toLocaleString()}</td>
                            </tr>`;
        });
        personsHtml += '</table>';
        document.getElementById('personsNetTable').innerHTML = personsHtml || '<div class="empty-list">هیڅ حساب نشته</div>';

        const ctx = document.getElementById('reportChart').getContext('2d');
        if (reportChart) reportChart.destroy();
        if (typeof Chart !== 'undefined') {
            reportChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: Object.keys(data.cash),
                    datasets: [{
                        label: 'موجودي',
                        data: Object.values(data.cash),
                        backgroundColor: '#f59e0b',
                        borderRadius: 8
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {
                        legend: { position: 'top' }
                    }
                }
            });
        }
    } catch (err) {
        console.error(err);
        showToast('د راپور لوډولو کې ستونزه', false);
        document.getElementById('currencyReportCards').innerHTML = '<div class="empty-list">د راپور معلومات نشته</div>';
        document.getElementById('personsNetTable').innerHTML = '<div class="empty-list">د خلکو حسابونه نشته</div>';
    } finally {
        showLoading(false);
    }
}
function refreshReport() { loadReport(); }
function printReport() { window.print(); }

// ==================== Settings ====================
async function loadRates() {
    try {
        const rates = await api.get('/api/get_all_rates');
        let html = '</table><th>له</th><th>ته</th><th>نرخ</th></tr>';
        rates.forEach(r => {
            html += `<tr>
                        <td>${r.from}</td>
                        <td>${r.to}</td>
                        <td><input type="number" id="rate_${r.from}_${r.to}" value="${r.rate}" step="any" class="input" style="max-width:130px;"></td>
                    </tr>`;
        });
        html += '</table>';
        document.getElementById('ratesPanel').innerHTML = html;
    } catch (err) {
        document.getElementById('ratesPanel').innerHTML = '<div class="empty-list">د نرخونو جدول نشته</div>';
    }
}

async function saveRates() {
    const inputs = document.querySelectorAll('[id^="rate_"]');
    for (const inp of inputs) {
        const parts = inp.id.split('_');
        const from = parts[1];
        const to = parts[2];
        const rate = parseFloat(inp.value);
        if (!isNaN(rate)) {
            try {
                await api.post('/api/update_exchange_rate', { from_curr: from, to_curr: to, rate });
            } catch (err) {
                console.warn(`نرخ ${from}->${to} خوندي نشو`, err);
            }
        }
    }
    showToast('نرخونه خوندي شول');
}

async function addNewCurrency() {
    const code = document.getElementById('newCurrencyCode').value.trim().toUpperCase();
    if (!code || code.length !== 3) {
        showToast('اسعار باید ۳ توري ولري (لکه EUR)', false);
        return;
    }
    try {
        const res = await api.post('/api/add_currency', { currency: code });
        if (res.success) {
            showToast(res.message);
            document.getElementById('newCurrencyCode').value = '';
            loadRates();
            loadCurrencies();
            loadCurrenciesForDelete();
        } else {
            showToast(res.message, false);
        }
    } catch (err) {
        showToast('د اسعارو اضافه کولو کې تېروتنه', false);
    }
}

async function changeCred() {
    const old = document.getElementById('currentPass').value;
    const newUser = document.getElementById('newUsername').value.trim();
    const newPass = document.getElementById('newPassword').value;
    if (!old) {
        showToast('اوسنی پاسورډ اړین دی', false);
        return;
    }
    try {
        const res = await api.post('/api/change_credentials', { old_pass: old, new_user: newUser, new_pass: newPass });
        if (res.success) {
            showToast(res.message);
            setTimeout(() => location.reload(), 2000);
        } else {
            showToast(res.message, false);
        }
    } catch (err) {
        showToast('د بدلولو تېروتنه', false);
    }
}

async function backupDatabase() {
    try {
        const res = await api.get('/api/backup_database');
        const msgSpan = document.getElementById('backupMsg');
        if (msgSpan) msgSpan.innerText = res.success ? `بیک اپ: ${res.file}` : 'نابریالی';
        showToast(res.success ? 'بیک اپ واخیستل شو' : 'تېروتنه', res.success);
    } catch (err) {
        showToast('د بیک اپ تېروتنه', false);
    }
}

// ==================== Startup ====================
window.addEventListener('load', async () => {
    showLoading(true);
    updateDate();
    setInterval(updateDate, 60000);

    try {
        await loadCurrencies();
        await loadDashboard();
        showLoading(false);
        console.log('سیستم په بریالیتوب سره پیل شو');

        setInterval(() => {
            if (document.getElementById('dashboard').classList.contains('active-page')) {
                loadDashboard();
            }
        }, 60000);
    } catch (err) {
        console.error('د پیلولو تېروتنه:', err);
        showToast('سیستم په بشپړه توګه پیل نشو: ' + (err.message || 'نامعلومه تېروتنه'), false);
        showLoading(false);
    }
});
