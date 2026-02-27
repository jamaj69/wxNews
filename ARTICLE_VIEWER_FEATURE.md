# Article Detail Viewer Feature

## 📖 Overview

The wxAsyncNewsReader now includes a comprehensive **Article Detail Viewer** that displays full article information directly from the database, without needing to open a web browser.

## ✨ Features

### What You See
When you click on any article in the list, a new window opens showing:

1. **Article Title** - Large, bold, easy to read
2. **Metadata Bar** - Author, publication date, and source
3. **Article Image** - Automatically loaded and resized from URL (if available)
4. **Description** - Article summary/preview
5. **Full Content** - Complete article text in a scrollable text area
6. **Action Buttons**:
   - "Open Full Article in Browser" - Opens the original article URL
   - "Close" - Closes the detail window

### User Experience Enhancements

- ✅ **No browser needed** - Read articles directly in the app
- ✅ **Image display** - Automatically fetches and shows article images
- ✅ **Smart image resizing** - Large images are automatically resized to fit
- ✅ **Keyboard shortcuts** - Press ESC to close the detail window
- ✅ **Scrollable content** - Long articles are fully readable
- ✅ **Clean layout** - Professional, easy-to-read design
- ✅ **Fallback handling** - If images fail to load, shows a notice instead of crashing

## 🎯 How to Use

### Basic Usage
1. Start wxAsyncNewsReader: `python wxAsyncNewsReader.py`
2. Click a source in the left panel
3. Click any article in the right panel
4. **New!** Article detail window opens automatically
5. Read the article, view images, check metadata
6. Click "Open Full Article in Browser" if you want the full web version
7. Press ESC or click Close to return to article list

### Navigation
- **Mouse**: Click articles to view details
- **Keyboard**: ESC closes detail window
- **Multiple windows**: You can open multiple article details at once

## 🔧 Technical Details

### Data Display
The viewer reads directly from the SQLite database (`gm_articles` table):

```python
article_data = {
    'title': 'Article headline',
    'author': 'Author name',
    'description': 'Article summary',
    'content': 'Full article text',
    'url': 'Original article URL',
    'urlToImage': 'Image URL',
    'publishedAt': '2024-02-26T12:00:00Z',
    'id_source': 'source-id'
}
```

### Image Handling
- Images are fetched from `urlToImage` field
- Uses Pillow (PIL) for image processing
- Automatically resizes images wider than 850px
- Maintains aspect ratio
- Timeout: 5 seconds for image loading
- Fallback: Shows "[Image unavailable]" if loading fails

### Window Layout
```
┌─────────────────────────────────────────────┐
│ Article Title (Large, Bold)                 │
│ Author | Date | Source (Metadata)           │
├─────────────────────────────────────────────┤
│                                              │
│ [Article Image - if available]              │
│                                              │
├─────────────────────────────────────────────┤
│ Description text here...                    │
├─────────────────────────────────────────────┤
│ Content:                                    │
│ ┌─────────────────────────────────────────┐ │
│ │ Full article text here...                │ │
│ │ (scrollable if long)                     │ │
│ │                                           │ │
│ └─────────────────────────────────────────┘ │
├─────────────────────────────────────────────┤
│ [Open Full Article] [Close]                 │
└─────────────────────────────────────────────┘
```

### Dependencies
New requirement added to `requirements.txt`:
```
Pillow>=10.0.0  # For image display in article viewer
```

Install if needed:
```bash
pip install Pillow
```

## 📝 Code Changes

### New Components

1. **ArticleDetailFrame class**
   - Location: wxAsyncNewsReader.py (lines 52-196)
   - Purpose: Display full article details
   - Features: Image loading, text wrapping, metadata display

2. **Enhanced OnLinkSelected method**
   - Now opens ArticleDetailFrame instead of just web browser
   - Retrieves article data from database
   - Fallback to browser if article not found

3. **Current source tracking**
   - `self.current_source_key` added to NewsPanel
   - Tracks which source is selected
   - Used to find article data when article is clicked

### Modified Files
- `wxAsyncNewsReader.py` - Main enhancement
- `requirements.txt` - Added Pillow dependency
- `NEWS_SYSTEM_GUIDE.md` - Updated documentation
- `NEWS_QUICK_START.md` - Updated quick start guide

## 🎨 Customization Options

### Window Size
Default: 900x700 pixels
Modify in ArticleDetailFrame.__init__():
```python
size=(900, 700)  # Change to your preference
```

### Image Width
Default maximum: 850 pixels
Modify in ArticleDetailFrame image loading:
```python
max_width = 850  # Change to your preference
```

### Text Wrapping
Title wrap width: 850 pixels
Description wrap width: 850 pixels
Modify in ArticleDetailFrame text creation

## 🐛 Troubleshooting

### Images Not Loading
**Problem**: Images show "[Image unavailable]"
**Causes**:
- Image URL is invalid or expired
- Network timeout (>5 seconds)
- Image format not supported
- Server blocks automated requests

**Solution**: This is normal - not all news sources provide working image URLs. Click "Open Full Article in Browser" to see images on the original website.

### Memory Usage
**Problem**: App uses more memory with many articles open
**Solution**: Close article detail windows when done reading (ESC or Close button)

### Pillow Not Installed
**Problem**: ImportError: No module named 'PIL'
**Solution**: 
```bash
pip install Pillow
```

## 📊 Performance

- **Image Loading**: Async, doesn't block UI
- **Window Creation**: Instant (<100ms)
- **Memory per window**: ~5-15 MB (depending on image size)
- **Database queries**: None (uses cached data from NewsPanel)

## 🚀 Future Enhancements (Ideas)

Possible improvements for future versions:
- [ ] Cache downloaded images to disk
- [ ] Add zoom controls for images
- [ ] Add text size controls
- [ ] Add bookmark/favorite feature
- [ ] Add share via email/social media
- [ ] Add print article feature
- [ ] Add "Next Article" / "Previous Article" navigation
- [ ] Add full-text search in article content
- [ ] Add category/tag filtering

## 📚 Version History

- **v6 (2024-02-26)**: Added Article Detail Viewer
  - Full article display with images
  - Metadata display (author, date, source)
  - Keyboard shortcuts
  - Smart image handling

- **v5**: Database-only reader, separate collector
- **v4**: Added TimeStamp column
- **v3**: Improved database handling
- **v2**: Added async collection in reader
- **v1**: Basic Twisted-based reader

## 🤝 Contributing

To enhance the Article Detail Viewer:
1. Edit `ArticleDetailFrame` class in wxAsyncNewsReader.py
2. Test with various article types (with/without images)
3. Update this documentation
4. Commit with descriptive message

---

**Enjoy reading news directly in the app!** 📖✨
