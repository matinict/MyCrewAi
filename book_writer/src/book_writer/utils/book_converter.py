# ============================================
# FILE: src/book_writer/utils/book_converter.py
# ============================================
import os
from pathlib import Path

def convert_markdown_to_formats(markdown_file, title, author, output_dir='output', output_prefix='final_book', language='en', subtitle=''):
    '''
    Convert markdown file to PDF and EPUB formats
    '''
    try:
        from markdown2 import markdown
        from weasyprint import HTML, CSS
        from ebooklib import epub
        
        # Read markdown content
        with open(markdown_file, 'r', encoding='utf-8') as f:
            md_content = f.read()
        
        # Convert markdown to HTML
        html_content = markdown(md_content, extras=['fenced-code-blocks', 'tables'])
        
        # Create PDF
        pdf_path = os.path.join(output_dir, f'{output_prefix}.pdf')
        create_pdf(html_content, title, author, pdf_path, language, subtitle)
        print(f"✅ PDF created: {pdf_path}")
        
        # Create EPUB
        epub_path = os.path.join(output_dir, f'{output_prefix}.epub')
        create_epub(md_content, title, author, epub_path, language, subtitle)
        print(f"✅ EPUB created: {epub_path}")
        
        return True
        
    except ImportError as e:
        print(f"Missing required library: {e}")
        print("\nInstall required packages:")
        print("uv add markdown2 weasyprint ebooklib")
        return False

def create_pdf(html_content, title, author, output_path, language='en', subtitle=''):
    '''Create PDF from HTML content with Bengali font support'''
    from weasyprint import HTML, CSS
    
    # Choose font based on language
    if language == 'bn':
        font_family = "'Noto Sans Bengali', 'Kalpurush', 'SolaimanLipi', sans-serif"
    else:
        font_family = "'Georgia', serif"
    
    # Format subtitle if provided
    subtitle_html = f'<p class="subtitle">{subtitle}</p>' if subtitle else ''
    
    # Add styling with Bengali font support
    styled_html = f'''
    <!DOCTYPE html>
    <html lang="{language}">
    <head>
        <meta charset="UTF-8">
        <title>{title}</title>
        <style>
            @page {{
                size: A4;
                margin: 2.5cm;
                @top-center {{
                    content: "{title}";
                    font-size: 10pt;
                    color: #666;
                }}
                @bottom-center {{
                    content: "Page " counter(page);
                    font-size: 10pt;
                }}
            }}
            body {{
                font-family: {font_family};
                font-size: 12pt;
                line-height: 1.8;
                color: #333;
            }}
            h1 {{
                font-size: 24pt;
                margin-top: 2em;
                margin-bottom: 1em;
                page-break-before: always;
                page-break-after: avoid;
            }}
            h1:first-of-type {{
                page-break-before: avoid;
            }}
            h2 {{
                font-size: 18pt;
                margin-top: 1.5em;
                margin-bottom: 0.75em;
                page-break-after: avoid;
            }}
            h3 {{
                font-size: 14pt;
                margin-top: 1em;
                margin-bottom: 0.5em;
                page-break-after: avoid;
            }}
            p {{
                text-align: justify;
                margin-bottom: 1em;
                orphans: 3;
                widows: 3;
            }}
            .title-page {{
                text-align: center;
                margin-top: 30%%;
                page-break-after: always;
            }}
            .title-page h1 {{
                font-size: 32pt;
                page-break-before: avoid;
                page-break-after: avoid;
                margin-bottom: 0.5em;
            }}
            .title-page .subtitle {{
                font-size: 16pt;
                margin-top: 1em;
                margin-bottom: 2em;
                color: #555;
                font-style: italic;
            }}
            .title-page .author {{
                font-size: 18pt;
                margin-top: 3em;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <div class="title-page">
            <h1>{title}</h1>
            {subtitle_html}
            <p class="author">by {author}</p>
        </div>
        {html_content}
    </body>
    </html>
    '''
    
    HTML(string=styled_html).write_pdf(output_path)

def create_epub(markdown_content, title, author, output_path, language='en', subtitle=''):
    '''Create EPUB from markdown content with Bengali support'''
    from ebooklib import epub
    
    book = epub.EpubBook()
    
    # Set metadata
    book.set_identifier(f'book_{title.replace(" ", "_")}')
    book.set_title(title)
    book.set_language(language)
    book.add_author(author)
    
    # Add subtitle to metadata if provided
    if subtitle:
        book.add_metadata('DC', 'description', subtitle)
    
    # Add CSS for Bengali font support
    if language == 'bn':
        style = '''
        body {
            font-family: 'Noto Sans Bengali', 'Kalpurush', 'SolaimanLipi', sans-serif;
            line-height: 1.8;
        }
        h1, h2, h3 {
            font-family: 'Noto Sans Bengali', 'Kalpurush', 'SolaimanLipi', sans-serif;
        }
        .subtitle {
            font-size: 1.2em;
            font-style: italic;
            color: #555;
            margin-bottom: 2em;
        }
        '''
    else:
        style = '''
        body {
            font-family: Georgia, serif;
            line-height: 1.6;
        }
        .subtitle {
            font-size: 1.2em;
            font-style: italic;
            color: #555;
            margin-bottom: 2em;
        }
        '''
    
    nav_css = epub.EpubItem(
        uid="style_nav",
        file_name="style/nav.css",
        media_type="text/css",
        content=style
    )
    book.add_item(nav_css)
    
    # Split content into chapters
    chapters = []
    chapter_contents = markdown_content.split('# ')
    
    for i, chapter_content in enumerate(chapter_contents[1:], 1):  # Skip first split
        chapter_title = chapter_content.split('\n')[0]
        chapter_body = '\n'.join(chapter_content.split('\n')[1:])
        
        # Create chapter
        c = epub.EpubHtml(
            title=chapter_title,
            file_name=f'chap_{i:02d}.xhtml',
            lang=language
        )
        c.content = f'<h1>{chapter_title}</h1>{chapter_body}'
        c.add_item(nav_css)
        book.add_item(c)
        chapters.append(c)
    
    # Add table of contents
    book.toc = tuple(chapters)
    
    # Add navigation files
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    
    # Define spine
    book.spine = ['nav'] + chapters
    
    # Write EPUB file
    epub.write_epub(output_path, book)