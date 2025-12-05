"""
EKAP İhale Arama Scraper
https://ekapv2.kik.gov.tr/ekap/search

Tüm ihaleleri çeker, bugünden itibaren 1 hafta içindekileri ve "Katılıma Açık" olanları filtreler.
Kullanım: python ekap_scraper.py
Gerekli: pip install playwright pandas openpyxl
         playwright install chromium
"""

from playwright.sync_api import sync_playwright
import pandas as pd
from datetime import datetime, timedelta


def get_date_range():
    """Bugün ve 1 hafta sonrasını DD.MM.YYYY formatında döndürür."""
    today = datetime.now()
    one_week_later = today + timedelta(days=7)
    return today.strftime('%d.%m.%Y'), one_week_later.strftime('%d.%m.%Y')


def setup_filters(page):
    """
    Sayfa filtrelerini ayarlar:
    - Tarih tipi: İhale Tarihi seçer
    - Tarih aralığı: bugün - 1 hafta sonra
    - Arama butonuna tıklar
    """
    start_date, end_date = get_date_range()
    print(f"\nFiltreler ayarlanıyor...")
    print(f"  Tarih aralığı: {start_date} - {end_date}")
    
    # Sayfanın tam yüklenmesini bekle
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(3000)
    
    try:
        # 1. Detaylı arama butonuna tıkla (scroll into view + force click)
        print("  [1/6] Detaylı arama açılıyor...")
        detail_button = page.locator('[data-testid="A392188"]')
        if detail_button.count() == 0:
            # Alternatif selector dene
            detail_button = page.locator('dx-button.btn.btn--light.btn--large.btn--with-icon')
        detail_button.first.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        detail_button.first.click(force=True)
        page.wait_for_timeout(1500)
        
        # 2. İhale Tarihi radio butonuna tıkla
        print("  [2/6] İhale Tarihi seçiliyor...")
        radio_buttons = page.locator('div.dx-radiobutton-icon')
        if radio_buttons.count() > 1:
            radio_buttons.nth(1).scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            radio_buttons.nth(1).click(force=True)
        page.wait_for_timeout(500)
        
        # 3. Tarih aralığı dropdown'ını aç
        print("  [3/6] Tarih aralığı açılıyor...")
        date_dropdown = page.locator('div.dx-dropdowneditor-icon').first
        date_dropdown.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        date_dropdown.click(force=True)
        page.wait_for_timeout(500)
        
        # 4. Başlangıç tarihini gir
        print(f"  [4/6] Başlangıç tarihi: {start_date}")
        start_input = page.locator('div.dx-start-datebox input.dx-texteditor-input')
        start_input.click(force=True)
        start_input.fill('')
        start_input.type(start_date, delay=30)
        page.keyboard.press('Enter')
        page.wait_for_timeout(500)
        
        # 5. Bitiş tarihini gir
        print(f"  [5/6] Bitiş tarihi: {end_date}")
        end_input = page.locator('div.dx-end-datebox input.dx-texteditor-input')
        end_input.click(force=True)
        end_input.fill('')
        end_input.type(end_date, delay=30)
        page.keyboard.press('Enter')
        page.wait_for_timeout(500)
        
        # 6. Arama butonuna tıkla
        print("  [6/6] Arama yapılıyor...")
        search_button = page.locator('#search-ihale')
        search_button.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        search_button.click(force=True)
        page.wait_for_timeout(3000)  # Sonuçların yüklenmesini bekle
        
        print("✓ Filtreler başarıyla uygulandı")
        
    except Exception as e:
        print(f"✗ Filtreleme hatası: {e}")
        import traceback
        traceback.print_exc()



def scrape_ihaleler(page, max_pages=None):
    """
    Tüm ihale-liste-item elementlerini scrape eder.
    
    Args:
        page: Playwright page nesnesi
        max_pages: Maksimum sayfa sayısı (None = tümü)
    
    Returns:
        Liste içinde dict'ler (her ihale bir dict)
    """
    all_ihaleler = []
    current_page = 1
    
    while True:
        print(f"\n{'='*50}")
        print(f"Sayfa {current_page} işleniyor...")
        print('='*50)
        
        if current_page > 30:
            print("Maksimum sayfa limiti aşıldı, çıkılıyor...")
            break
        
        # Sayfanın yüklenmesini bekle
        try:
            page.wait_for_selector('ihale-liste-item', timeout=30000)
        except:
            print("İhale bulunamadı, çıkılıyor...")
            break
            
        page.wait_for_timeout(2000)  # Ekstra bekleme (dinamik içerik için)
        
        # Tüm ihale-liste-item elementlerini bul
        items = page.locator('ihale-liste-item').all()
        print(f"Bu sayfada {len(items)} ihale bulundu")
        
        for i, item in enumerate(items):
            try:
                ihale = extract_ihale_data(item)
                all_ihaleler.append(ihale)
                print(f"  [{i+1}] {ihale.get('ikn', 'N/A')} - {ihale.get('ihale_turu', 'N/A')} - {ihale.get('ihale', 'N/A')[:40]}...")
            except Exception as e:
                print(f"  [{i+1}] Hata: {e}")
        
        # Sonraki sayfa kontrolü
        if max_pages and current_page >= max_pages:
            print(f"\nMaksimum sayfa sayısına ({max_pages}) ulaşıldı.")
            break
        
        # Sonraki sayfa butonunu bul ve tıkla
        next_button = page.locator('i.dx-icon.fa-solid.fa-chevron-right')
        
        if next_button.count() > 0:
            try:
                # Butonun tıklanabilir olup olmadığını kontrol et
                parent_button = next_button.first.locator('xpath=ancestor::dx-button')
                if parent_button.count() > 0 and not parent_button.is_disabled():
                    next_button.first.click()
                    page.wait_for_timeout(2000)
                    current_page += 1
                else:
                    print("\nSon sayfaya ulaşıldı.")
                    break
            except:
                print("\nSon sayfaya ulaşıldı.")
                break
        else:
            print("\nSon sayfaya ulaşıldı.")
            break
    
    return all_ihaleler


def extract_ihale_data(item):
    """
    Tek bir ihale-liste-item elementinden verileri çıkarır.
    
    Args:
        item: Playwright locator (ihale-liste-item elementi)
    
    Returns:
        Dict: İhale verileri
    """
    data = {}
    
    # İhale adı
    ihale_loc = item.locator('span.ihale')
    data['ihale'] = safe_get_text(ihale_loc)
    
    # IKN (İhale Kayıt Numarası)
    ikn_loc = item.locator('span.ikn')
    data['ikn'] = safe_get_text(ikn_loc)
    
    # İl ve Saat bilgisi
    il_saat_loc = item.locator('span.il-saat')
    data['il_saat'] = safe_get_text(il_saat_loc)
    
    # İhale Türü - TÜM badge'leri kontrol et (Hizmet, Mal, Yapım, Danışmanlık)
    # badge--danger genelde ihale türünü gösterir
    # Tüm span.badge elementlerini kontrol ediyoruz
    ihale_turu = ''
    
    # Önce badge--large olanları dene (bunlar genelde tür bilgisi)
    badge_large_locs = item.locator('span.badge.badge--large')
    if badge_large_locs.count() > 0:
        for i in range(badge_large_locs.count()):
            badge_text = safe_get_text(badge_large_locs.nth(i))
            # İhale türlerini kontrol et
            if badge_text in ['Hizmet', 'Mal', 'Yapım', 'Danışmanlık']:
                ihale_turu = badge_text
                break
    
    # Eğer bulunamadıysa tüm badge'lere bak
    if not ihale_turu:
        all_badges = item.locator('span.badge')
        if all_badges.count() > 0:
            for i in range(all_badges.count()):
                badge_text = safe_get_text(all_badges.nth(i))
                if badge_text in ['Hizmet', 'Mal', 'Yapım', 'Danışmanlık']:
                    ihale_turu = badge_text
                    break
    
    data['ihale_turu'] = ihale_turu
    
    # Katılım durumu (badge--success olanlar genelde katılım bilgisi)
    badge_success_loc = item.locator('span.badge.badge--success')
    data['katilim_durumu'] = safe_get_text(badge_success_loc)
    
    # Tüm badge metinlerini de kaydedelim (debug için)
    all_badges = item.locator('span.badge')
    badge_texts = []
    if all_badges.count() > 0:
        for i in range(all_badges.count()):
            text = safe_get_text(all_badges.nth(i))
            if text:
                badge_texts.append(text)
    data['tum_badgeler'] = ' | '.join(badge_texts)
    
    return data


def safe_get_text(locator):
    """
    Locator'dan güvenli şekilde text alır.
    Element yoksa boş string döner.
    """
    try:
        if locator.count() > 0:
            return (locator.first.text_content() or '').strip()
    except:
        pass
    return ''


def process_data(ihaleler):
    """
    Çekilen verileri işler ve filtreler.
    
    İşlemler:
    1. tum_badgeler sütununu sil
    2. il_saat sütununu il ve tarih olarak ayır
    3. Tarih: bugünden itibaren 1 hafta içindekiler (filter in)
    4. katilim_durumu: virgülden sonrasını al, "Katılıma Açık" olmayanları filter out
    
    Returns:
        pd.DataFrame: İşlenmiş ve filtrelenmiş veri
    """
    df = pd.DataFrame(ihaleler)
    
    print(f"\n{'='*50}")
    print("VERİ İŞLEME")
    print('='*50)
    print(f"Başlangıç kayıt sayısı: {len(df)}")
    
    # 1. tum_badgeler sütununu sil
    if 'tum_badgeler' in df.columns:
        df = df.drop(columns=['tum_badgeler'])
        print("✓ tum_badgeler sütunu silindi")
    
    # 2. il_saat sütununu ayır (virgülden böl)
    if 'il_saat' in df.columns:
        # Virgülden böl: "İstanbul, 10.12.2024 14:30" -> ["İstanbul", " 10.12.2024 14:30"]
        split_data = df['il_saat'].str.split(',', n=1, expand=True)
        df['il'] = split_data[0].str.strip() if 0 in split_data.columns else ''
        df['tarih_str'] = split_data[1].str.strip() if 1 in split_data.columns else ''
        
        # Tarih sütununu datetime'a çevir (dd.MM.yyyy HH:mm formatı)
        df['tarih'] = pd.to_datetime(df['tarih_str'], format='%d.%m.%Y %H:%M', errors='coerce')
        
        # Orijinal il_saat sütununu sil
        df = df.drop(columns=['il_saat', 'tarih_str'])
        print("✓ il_saat sütunu 'il' ve 'tarih' olarak ayrıldı")
    
    # 3. Tarih filtresi: bugünden itibaren 1 hafta içindekiler
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    one_week_later = today + timedelta(days=7)
    
    print(f"  Tarih aralığı: {today.strftime('%d.%m.%Y')} - {one_week_later.strftime('%d.%m.%Y')}")
    
    #before_filter = len(df)
    #df = df[df['tarih'].notna()]  # NaT olanları çıkar
    #df = df[(df['tarih'].dt.date >= today.date()) & (df['tarih'].dt.date <= one_week_later.date())]
    #print(f"✓ Tarih filtresi uygulandı: {before_filter} -> {len(df)} kayıt")
    
    # 4. katilim_durumu: virgülden sonrasını al ve "Katılıma Açık" filtrele
    if 'katilim_durumu' in df.columns:
        # Virgülden sonrasını al: "Açık İhale, Katılıma Açık" -> "Katılıma Açık"
        df['katilim_durumu'] = df['katilim_durumu'].apply(
            lambda x: x.split(',')[-1].strip() if pd.notna(x) and ',' in str(x) else str(x).strip()
        )
        
        before_filter = len(df)
        df = df[df['katilim_durumu'] == 'Katılıma Açık']
        print(f"✓ Katılım filtresi uygulandı: {before_filter} -> {len(df)} kayıt (sadece 'Katılıma Açık')")
    
    # Sütun sırasını düzenle
    column_order = ['ikn', 'ihale', 'ihale_turu', 'il', 'tarih', 'katilim_durumu']
    existing_columns = [col for col in column_order if col in df.columns]
    df = df[existing_columns]
    
    print(f"\nSonuç: {len(df)} ihale")
    
    return df


def save_to_csv(df, filename=None):
    """Verileri CSV dosyasına kaydeder."""
    if not filename:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'ekap_ihaleler_{timestamp}.csv'
    
    df.to_csv(filename, index=False, encoding='utf-8-sig')
    print(f"\n✓ CSV kaydedildi: {filename}")
    return filename


def save_to_excel(df, filename=None):
    """Verileri Excel dosyasına kaydeder."""
    if not filename:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'ekap_ihaleler_{timestamp}.xlsx'
    
    with pd.ExcelWriter(filename, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='İhaleler', index=False)
        
        # Sütun genişliklerini ayarla
        worksheet = writer.sheets['İhaleler']
        for i, col in enumerate(df.columns):
            max_length = max(
                df[col].astype(str).map(len).max(),
                len(col)
            ) + 2
            # Excel sütun harfi hesapla (A, B, ... Z, AA, AB, ...)
            col_letter = get_column_letter(i + 1)
            worksheet.column_dimensions[col_letter].width = min(max_length, 50)
    
    print(f"✓ Excel kaydedildi: {filename}")
    return filename


def get_column_letter(col_idx):
    """Sütun indeksini Excel harf karşılığına çevirir (1=A, 2=B, ... 27=AA)"""
    result = ""
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        result = chr(65 + remainder) + result
    return result


def main():
    """Ana fonksiyon"""
    url = "https://ekapv2.kik.gov.tr/ekap/search"
    
    print("="*60)
    print("EKAP İhale Scraper")
    print("="*60)
    print(f"URL: {url}")
    print(f"Başlangıç: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    with sync_playwright() as p:
        # Tarayıcıyı başlat
        browser = p.chromium.launch(
            headless=False,  # True yaparsanız tarayıcı görünmez
            slow_mo=100      # Hareketleri yavaşlat (debug için)
        )
        
        # Yeni sayfa aç
        page = browser.new_page()
        page.set_viewport_size({"width": 1920, "height": 1080})
        
        try:
            # Sayfaya git
            print(f"\nSayfa yükleniyor: {url}")
            page.goto(url, wait_until='networkidle')
            
            # Filtreleri ayarla (tarih aralığı)
            setup_filters(page)
            
            # İhaleleri scrape et (max_pages=None tüm sayfalar için)
            ihaleler = scrape_ihaleler(page, max_pages=None)
            
            if ihaleler:
                print(f"\n{'='*60}")
                print(f"TOPLAM {len(ihaleler)} İHALE ÇEKİLDİ")
                print('='*60)
                
                # Veriyi işle ve filtrele
                df = process_data(ihaleler)
                
                if len(df) > 0:
                    # Verileri kaydet
                    csv_file = save_to_csv(df)
                    excel_file = save_to_excel(df)
                    
                    # İhale türü dağılımı
                    print(f"\nİhale Türü Dağılımı:")
                    print(df['ihale_turu'].value_counts().to_string())
                    
                    # İl dağılımı
                    print(f"\nİl Dağılımı (ilk 10):")
                    print(df['il'].value_counts().head(10).to_string())
                    
                    # Özet tablo göster
                    print(f"\nÖzet (ilk 10 kayıt):")
                    print(df.head(10).to_string())
                else:
                    print("\n⚠ Filtreleme sonrası kayıt kalmadı!")
            else:
                print("\n⚠ Hiç ihale bulunamadı!")
                
        except Exception as e:
            print(f"\n✗ Hata oluştu: {e}")
            import traceback
            traceback.print_exc()
        finally:
            browser.close()
    
    print(f"\nBitiş: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
