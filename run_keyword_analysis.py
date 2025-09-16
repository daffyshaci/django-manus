#!/usr/bin/env python3
"""
Script Utama untuk Analisis Keyword Google Search Console
"""

import json
import pandas as pd
from datetime import datetime, timedelta
from google_search_console_api import authenticate, get_search_analytics
from advanced_keyword_analysis import AdvancedKeywordAnalysis

def load_config(config_file='config.json'):
    """Memuat konfigurasi dari file JSON"""
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"File config {config_file} tidak ditemukan. Menggunakan config default.")
        return {
            "service_account_file": "service-account-key.json",
            "site_url": "https://example.com/",
            "days_back": 90
        }

def main():
    print("=== SCRIPT ANALISIS KEYWORD GOOGLE SEARCH CONSOLE ===\n")
    
    # Load konfigurasi
    config = load_config()
    
    # Autentikasi
    print("1. Melakukan autentikasi...")
    service = authenticate(config.get('service_account_file'))
    
    if not service:
        print("Autentikasi gagal. Pastikan file service account valid.")
        return
    
    # Parameter analisis
    days_back = config.get('days_back', 90)
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    
    print(f"2. Mengambil data dari {start_date} hingga {end_date}...")
    
    # Ambil data dasar
    data = get_search_analytics(
        service,
        start_date=start_date,
        end_date=end_date,
        dimensions=['query'],
        row_limit=25000
    )
    
    if not data:
        print("Tidak ada data yang ditemukan.")
        return
    
    print(f"3. Data berhasil diambil: {len(data)} rows")
    
    # Analisis dasar
    print("4. Melakukan analisis dasar...")
    df_basic = pd.DataFrame([{
        'keyword': row['keys'][0],
        'clicks': row.get('clicks', 0),
        'impressions': row.get('impressions', 0),
        'ctr': row.get('ctr', 0),
        'position': row.get('position', 0)
    } for row in data])
    
    # Analisis lanjutan
    print("5. Melakukan analisis lanjutan...")
    analyzer = AdvancedKeywordAnalysis(
        config.get('service_account_file'),
        config.get('site_url')
    )
    
    # Cluster analysis
    clusters = analyzer.analyze_keyword_clusters(data)
    
    # Content gap analysis
    gaps = analyzer.identify_content_gaps(data)
    
    # Content ideas generation
    content_ideas = analyzer.generate_content_ideas(data)
    
    # Simpan hasil
    print("6. Menyimpan hasil analisis...")
    
    # Buat directory results jika belum ada
    import os
    os.makedirs('results', exist_ok=True)
    
    # Save basic analysis
    df_basic.to_csv('results/basic_keyword_analysis.csv', index=False)
    
    # Save clusters
    with pd.ExcelWriter('results/keyword_clusters.xlsx') as writer:
        for topic, keywords in clusters.items():
            keywords.to_excel(writer, sheet_name=topic[:30], index=False)
    
    # Save content gaps
    with pd.ExcelWriter('results/content_gaps.xlsx') as writer:
        gaps['good_position_low_imp'].to_excel(writer, sheet_name='Good_Position_Low_Imp', index=False)
        gaps['high_imp_bad_position'].to_excel(writer, sheet_name='High_Imp_Bad_Position', index=False)
        gaps['low_ctr_keywords'].to_excel(writer, sheet_name='Low_CTR_Keywords', index=False)
    
    # Save content ideas
    if not content_ideas.empty:
        content_ideas.to_csv('results/content_ideas.csv', index=False)
    
    # Generate report
    print("7. Membuat laporan summary...")
    generate_summary_report(df_basic, clusters, gaps, content_ideas)
    
    print("\n=== ANALISIS SELESAI ===")
    print("File hasil disimpan di folder 'results/'")

def generate_summary_report(df_basic, clusters, gaps, content_ideas):
    """Generate laporan summary"""
    report = []
    
    report.append("=== LAPORAN ANALISIS KEYWORD ===\n")
    
    # Basic stats
    total_keywords = len(df_basic)
    total_clicks = df_basic['clicks'].sum()
    total_impressions = df_basic['impressions'].sum()
    avg_position = df_basic['position'].mean()
    avg_ctr = df_basic['ctr'].mean()
    
    report.append(f"Total Keywords: {total_keywords}")
    report.append(f"Total Clicks: {total_clicks}")
    report.append(f"Total Impressions: {total_impressions}")
    report.append(f"Rata-rata Position: {avg_position:.2f}")
    report.append(f"Rata-rata CTR: {avg_ctr:.3f}\n")
    
    # Top performing keywords
    top_clicks = df_basic.nlargest(5, 'clicks')[['keyword', 'clicks', 'ctr']]
    top_impressions = df_basic.nlargest(5, 'impressions')[['keyword', 'impressions', 'position']]
    
    report.append("=== TOP 5 KEYWORDS BY CLICKS ===")
    for _, row in top_clicks.iterrows():
        report.append(f"{row['keyword']}: {row['clicks']} clicks (CTR: {row['ctr']:.3f})")
    
    report.append("\n=== TOP 5 KEYWORDS BY IMPRESSIONS ===")
    for _, row in top_impressions.iterrows():
        report.append(f"{row['keyword']}: {row['impressions']} impressions (Position: {row['position']:.1f})")
    
    # Cluster summary
    report.append("\n=== KEYWORD CLUSTERS ===")
    for topic, keywords in clusters.items():
        report.append(f"{topic}: {len(keywords)} keywords")
    
    # Content opportunities
    report.append("\n=== PELUANG KONTEN ===")
    report.append(f"Keyword dengan posisi baik tapi impressions rendah: {len(gaps['good_position_low_imp'])}")
    report.append(f"Keyword dengan impressions tinggi tapi posisi buruk: {len(gaps['high_imp_bad_position'])}")
    report.append(f"Ide konten yang dihasilkan: {len(content_ideas) if not content_ideas.empty else 0}")
    
    # Save report
    with open('results/summary_report.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))
    
    # Print summary to console
    print('\n'.join(report[:20]))  # Print first 20 lines

if __name__ == "__main__":
    main()