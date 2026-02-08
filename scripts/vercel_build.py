#!/usr/bin/env python3
"""
Build script for Vercel deployment.

This script generates the static site from pre-processed data in data/linked/.
It's optimized for fast builds by skipping the document processing stages
(discover, extract, detect, link) which are handled by GitHub Actions workflows.
"""

import sys
import json
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from mandate_pipeline.generation import (
    generate_unified_explorer_page,
    generate_signals_info_page,
    generate_data_json,
    build_igov_decision_documents,
    ensure_document_sessions,
    get_un_document_url,
)
from mandate_pipeline.detection import load_checks
from mandate_pipeline.extractor import _clean_paragraph_text
from mandate_pipeline.igov import load_igov_decisions_all


def main():
    """Generate static site for Vercel deployment."""
    print("=" * 60)
    print("Vercel Build: Mandate Pipeline Static Site Generator")
    print("=" * 60)
    
    start_time = time.time()
    
    # Load pre-processed documents
    print("\n📂 Loading documents from data/linked/...")
    linked_dir = Path('data/linked')
    documents = []
    
    if linked_dir.exists():
        for linked_file in sorted(linked_dir.glob('*.json')):
            if linked_file.name == 'index.json':
                continue
            try:
                with open(linked_file) as f:
                    doc = json.load(f)
                    documents.append(doc)
            except Exception as e:
                print(f"⚠️  Error loading {linked_file}: {e}")
    
    print(f"✅ Loaded {len(documents)} documents")

    # Add UN document URLs
    for doc in documents:
        if not doc.get('un_url') and doc.get('symbol'):
            doc['un_url'] = get_un_document_url(doc['symbol'])
    
    if not documents:
        print("⚠️  No documents found in data/linked/")
        print("   This is expected for PR previews before data pipeline runs.")
        print("   Creating minimal site...")
    
    # Enrich documents with paragraph text from extracted data
    print("\n📝 Enriching with paragraph text...")
    extracted_dir = Path('data/extracted')
    enriched_count = 0
    if extracted_dir.exists():
        extracted_by_stem = {}
        for ef in extracted_dir.glob('*.json'):
            extracted_by_stem[ef.stem] = ef

        for doc in documents:
            stem = doc.get('symbol', '').replace('/', '_')
            extracted_file = extracted_by_stem.get(stem)
            if extracted_file:
                try:
                    with open(extracted_file) as f:
                        extracted = json.load(f)
                    if extracted.get('paragraphs'):
                        doc['paragraphs'] = {
                            k: _clean_paragraph_text(v)
                            for k, v in extracted['paragraphs'].items()
                        }
                        if not doc.get('title'):
                            doc['title'] = extracted.get('title', '')
                        enriched_count += 1
                except Exception as e:
                    print(f"⚠️  Error enriching {doc.get('symbol')}: {e}")

    print(f"✅ Enriched {enriched_count}/{len(documents)} documents with paragraph text")

    # Build signal_paragraphs for documents that have paragraphs and signals
    print("\n🔗 Building signal paragraphs...")
    sp_count = 0
    for doc in documents:
        if doc.get('signal_paragraphs'):
            # Clean pre-existing signal paragraph text
            for sp in doc['signal_paragraphs']:
                if sp.get('text'):
                    sp['text'] = _clean_paragraph_text(sp['text'])
            sp_count += 1
            continue
        signal_paras = []
        for para_num, para_signals in doc.get('signals', {}).items():
            if para_signals:
                para_text = doc.get('paragraphs', {}).get(str(para_num), '')
                signal_paras.append({
                    'number': para_num,
                    'text': para_text,
                    'signals': para_signals,
                })
        if signal_paras:
            signal_paras.sort(key=lambda p: int(p['number']) if str(p['number']).isdigit() else 0)
            doc['signal_paragraphs'] = signal_paras
            sp_count += 1

    print(f"✅ {sp_count} documents have signal paragraphs")
    
    # Load signal detection rules
    print("\n🔍 Loading signal detection rules...")
    checks_file = Path('config/checks.yaml')
    checks = load_checks(checks_file) if checks_file.exists() else []
    print(f"✅ Loaded {len(checks)} signal types")
    
    # Load IGov decisions
    print("\n📋 Loading IGov decisions...")
    data_dir = Path('data')
    igov_decisions = []
    
    if data_dir.exists():
        try:
            igov_decisions = build_igov_decision_documents(
                load_igov_decisions_all(data_dir), checks
            )
            documents = documents + igov_decisions
            ensure_document_sessions(documents)
            print(f"✅ Loaded {len(igov_decisions)} IGov decisions")
        except Exception as e:
            print(f"⚠️  Error loading IGov decisions: {e}")
    
    # Generate static site
    print("\n🏗️  Generating static site...")
    output_dir = Path('docs')
    output_dir.mkdir(exist_ok=True)
    
    try:
        generate_unified_explorer_page(documents, checks, output_dir)
        generate_signals_info_page(checks, output_dir)
        generate_data_json(documents, checks, output_dir)
        print(f"✅ Generated site to {output_dir}/")
    except Exception as e:
        print(f"❌ Error generating site: {e}")
        raise
    
    # Summary
    duration = time.time() - start_time
    docs_with_signals = len([d for d in documents if d.get('signal_summary')])
    
    print("\n" + "=" * 60)
    print("📊 Build Summary")
    print("=" * 60)
    print(f"Documents processed:    {len(documents)}")
    print(f"Documents with signals: {docs_with_signals}")
    print(f"IGov decisions:         {len(igov_decisions)}")
    print(f"Signal types:           {len(checks)}")
    print(f"Build time:             {duration:.2f}s")
    
    # Check output files
    index_html = output_dir / 'index.html'
    data_json = output_dir / 'data.json'
    
    if index_html.exists():
        size_kb = index_html.stat().st_size / 1024
        print(f"index.html:             {size_kb:.1f} KB")
    
    if data_json.exists():
        size_kb = data_json.stat().st_size / 1024
        print(f"data.json:              {size_kb:.1f} KB")
    
    print("=" * 60)
    print("✅ Build complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()
