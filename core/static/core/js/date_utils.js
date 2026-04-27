/**
 * date_utils.js
 * Dinamik tarih seçenekleri ve hesaplama — ortak kullanım için.
 * SAP tarih formatı: DD.MM.YYYY
 */

const SAP_DATE_OPTIONS = [
    { value: '',                label: '— Seçiniz —',          disabled: true },
    { value: 'today',           label: 'Bugün' },
    { value: 'year_start',      label: 'Bu yılın başı' },
    { value: 'month_start',     label: 'Bu ayın başı' },
    { value: 'year_end',        label: 'Bu yılın sonu' },
    { value: 'month_end',       label: 'Bu ayın sonu' },
    { value: 'prev_month_start',label: 'Önceki ayın başı' },
    { value: 'prev_month_end',  label: 'Önceki ayın sonu' },
    { value: 'month_5',         label: 'Bu ayın 5\'i' },
    { value: 'prev_year_start', label: 'Geçen yılın başı' },
    { value: 'days_15',         label: '15 gün önce' },
    { value: 'days_30',         label: '30 gün önce' },
    { value: 'days_45',         label: '45 gün önce' },
    { value: 'days_60',         label: '60 gün önce' },
    { value: 'days_365',        label: '365 gün önce' },
];

/**
 * Verilen anahtar için bugüne göre tarih hesaplar.
 * @param {string} key – SAP_DATE_OPTIONS içindeki value
 * @returns {string} DD.MM.YYYY formatında tarih veya ''
 */
function calcDynamicDate(key) {
    const now  = new Date();
    const y    = now.getFullYear();
    const m    = now.getMonth(); // 0-based
    let d;

    switch (key) {
        case 'today':           d = new Date(y, m, now.getDate()); break;
        case 'year_start':       d = new Date(y, 0, 1); break;
        case 'month_start':      d = new Date(y, m, 1); break;
        case 'year_end':         d = new Date(y, 11, 31); break;
        case 'month_end':        d = new Date(y, m + 1, 0); break;
        case 'prev_month_start': d = new Date(y, m - 1, 1); break;
        case 'prev_month_end':   d = new Date(y, m, 0); break;
        case 'month_5':          d = new Date(y, m, 5); break;
        case 'prev_year_start':  d = new Date(y - 1, 0, 1); break;
        case 'days_15':          d = new Date(now - 15  * 86400000); break;
        case 'days_30':          d = new Date(now - 30  * 86400000); break;
        case 'days_45':          d = new Date(now - 45  * 86400000); break;
        case 'days_60':          d = new Date(now - 60  * 86400000); break;
        case 'days_365':         d = new Date(now - 365 * 86400000); break;
        default: return '';
    }

    const dd   = String(d.getDate()).padStart(2, '0');
    const mm   = String(d.getMonth() + 1).padStart(2, '0');
    const yyyy = d.getFullYear();
    return `${dd}.${mm}.${yyyy}`;
}
