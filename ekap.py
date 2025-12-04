"""
EKAP İhale Arama Scraper
https://ekapv2.kik.gov.tr/ekap/search

Bugün + 1 hafta sonrasına kadar olan tüm ihaleleri çekip CSV/Excel formatında kaydeder.
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
    - Tarih aralığı (bugün - 1 hafta sonra)
    - Sayfa başına 50 ihale
    """
    start_date, end_date = get_date_range()
    print(f"Tarih aralığı: {start_date} - {end_date}")
    
    # Sayfanın tam yüklenmesini bekle
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(2000)
    
    # 1. Tarih aralığı dropdown'ını aç
    print("Tarih filtresi ayarlanıyor...")
    try:
        # Tarih dropdown ikonuna tıkla
        date_dropdown = page.locator('div.dx-dropdowneditor-icon').first
        date_dropdown.click()
        page.wait_for_timeout(500)
    except:
        print("  Tarih dropdown bulunamadı, devam ediliyor...")
    
    # 2. Başlangıç tarihini gir
    try:
        start_input = page.locator('div.dx-start-datebox input.dx-texteditor-input').first
        start_input.click()
        start_input.fill('')
        start_input.type(start_date, delay=50)
        page.wait_for_timeout(300)
        print(f"  Başlangıç tarihi: {start_date}")
    except Exception as e:
        print(f"  Başlangıç tarihi hatası: {e}")
    
    # 3. Bitiş tarihini gir
    try:
        end_input = page.locator('div.dx-end-datebox input.dx-texteditor-input').first
        end_input.click()
        end_input.fill('')
        end_input.type(end_date, delay=50)
        page.wait_for_timeout(300)
        print(f"  Bitiş tarihi: {end_date}")
    except Exception as e:
        print(f"  Bitiş tarihi hatası: {e}")
    
    # 4. Sayfa başına 50 ihale seç
    print("Sayfa başına 50 ihale ayarlanıyor...")
    try:
        # Page size dropdown'ını bul ve tıkla
        page_size_dropdown = page.locator('dx-select-box.page-box')
        page_size_dropdown.click()
        page.wait_for_timeout(500)
        
        # 50 seçeneğini seç
        option_50 = page.locator('div.dx-item-content').filter(has_text='50')
        option_50.click()
        page.wait_for_timeout(500)
        print("  Sayfa boyutu: 50")
    except Exception as e:
        print(f"  Sayfa boyutu hatası: {e}")
    
    # 5. Arama butonuna tıkla
    print("Arama yapılıyor...")
    try:
        search_button = page.locator('#search-ihale')
        search_button.click()
        page.wait_for_timeout(3000)  # Sonuçların yüklenmesini bekle
        print("  Arama tamamlandı")
    except Exception as e:
        print(f"  Arama hatası: {e}")
    
    # Overlay varsa kapat
    try:
        overlay = page.locator('div.overlay')
        if overlay.count() > 0 and overlay.is_visible():
            overlay.click()
            page.wait_for_timeout(500)
    except:
        pass


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


def save_to_csv(data, filename=None):
    """Verileri CSV dosyasına kaydeder."""
    if not filename:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'ekap_ihaleler_{timestamp}.csv'
    
    df = pd.DataFrame(data)
    df.to_csv(filename, index=False, encoding='utf-8-sig')
    print(f"\n✓ CSV kaydedildi: {filename}")
    return filename


def save_to_excel(data, filename=None):
    """Verileri Excel dosyasına kaydeder."""
    if not filename:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'ekap_ihaleler_{timestamp}.xlsx'
    
    df = pd.DataFrame(data)
    
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
    start_date, end_date = get_date_range()
    
    print("="*60)
    print("EKAP İhale Scraper")
    print("="*60)
    print(f"URL: {url}")
    print(f"Tarih Aralığı: {start_date} - {end_date}")
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
            
            # Filtreleri ayarla (tarih + sayfa boyutu)
            setup_filters(page)
            
            # İhaleleri scrape et (max_pages=None tüm sayfalar için)
            ihaleler = scrape_ihaleler(page, max_pages=None)
            
            if ihaleler:
                print(f"\n{'='*60}")
                print(f"TOPLAM {len(ihaleler)} İHALE BULUNDU")
                print('='*60)
                
                # Verileri kaydet
                csv_file = save_to_csv(ihaleler)
                excel_file = save_to_excel(ihaleler)
                
                # İhale türü dağılımı
                df = pd.DataFrame(ihaleler)
                print(f"\nİhale Türü Dağılımı:")
                print(df['ihale_turu'].value_counts().to_string())
                
                # Özet tablo göster
                print(f"\nÖzet (ilk 10 kayıt):")
                print(df[['ikn', 'ihale_turu', 'il_saat', 'ihale']].head(10).to_string())
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
