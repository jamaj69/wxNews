#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Language Detection and Translation Service
Provides affordable language detection and translation for news articles.

Supported Services:
- Language Detection: langdetect (free, offline)
- Translation: 
  * googletrans (free Google Translate API)
  * deep-translator (multiple free backends)
  * argostranslate (free, offline)
"""

import asyncio
import logging
from typing import Optional, Dict, Tuple
from enum import Enum

# Language Detection
try:
    from langdetect import detect, detect_langs, LangDetectException
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False
    logging.warning("langdetect not installed. Run: pip install langdetect")

# Translation Services
try:
    from googletrans import Translator as GoogleTranslator
    GOOGLETRANS_AVAILABLE = True
except ImportError:
    GOOGLETRANS_AVAILABLE = False
    logging.warning("googletrans not installed. Run: pip install googletrans==4.0.0rc1")

try:
    from deep_translator import GoogleTranslator as DeepGoogleTranslator
    DEEP_TRANSLATOR_AVAILABLE = True
except ImportError:
    DEEP_TRANSLATOR_AVAILABLE = False
    logging.warning("deep-translator not installed. Run: pip install deep-translator")


class TranslationBackend(Enum):
    """Available translation backends"""
    GOOGLETRANS = "googletrans"  # Free Google Translate API
    DEEP_TRANSLATOR = "deep_translator"  # Multiple free backends
    NONE = "none"  # No translation


class LanguageService:
    """Service for detecting and translating article text"""
    
    def __init__(self, 
                 translation_backend: TranslationBackend = TranslationBackend.GOOGLETRANS,
                 target_language: str = 'pt',
                 enable_translation: bool = True):
        """
        Initialize language service
        
        Args:
            translation_backend: Which translation service to use
            target_language: Target language code (pt, en, es, etc.)
            enable_translation: Whether to enable translation
        """
        self.translation_backend = translation_backend
        self.target_language = target_language
        self.enable_translation = enable_translation
        self.logger = logging.getLogger(__name__)
        
        # Initialize translators
        self.google_translator = None
        self.deep_translator = None
        
        if enable_translation:
            self._init_translators()
    
    def _init_translators(self):
        """Initialize available translation backends"""
        if self.translation_backend == TranslationBackend.GOOGLETRANS and GOOGLETRANS_AVAILABLE:
            try:
                self.google_translator = GoogleTranslator()
                self.logger.info("✅ Google Translator initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize Google Translator: {e}")
        
        elif self.translation_backend == TranslationBackend.DEEP_TRANSLATOR and DEEP_TRANSLATOR_AVAILABLE:
            try:
                # Deep translator is initialized per-request with source/target
                self.logger.info("✅ Deep Translator backend ready")
            except Exception as e:
                self.logger.error(f"Failed to initialize Deep Translator: {e}")
    
    def detect_language(self, text: str) -> Optional[Dict[str, any]]:
        """
        Detect language of text
        
        Args:
            text: Text to analyze
            
        Returns:
            Dict with 'language' (code), 'confidence' (float), 'probabilities' (list)
            Returns None if detection fails
        """
        if not LANGDETECT_AVAILABLE:
            self.logger.warning("langdetect not available")
            return None
        
        if not text or len(text.strip()) < 10:
            return None
        
        try:
            # Get detailed probabilities
            probs = detect_langs(text)
            top_lang = probs[0]
            
            return {
                'language': top_lang.lang,
                'confidence': round(top_lang.prob, 4),
                'probabilities': [
                    {'lang': p.lang, 'prob': round(p.prob, 4)} 
                    for p in probs[:3]  # Top 3 languages
                ]
            }
        except LangDetectException as e:
            self.logger.debug(f"Language detection failed: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error in language detection: {e}")
            return None
    
    async def translate_text(self, 
                            text: str, 
                            source_lang: Optional[str] = None,
                            dest_lang: Optional[str] = None) -> Optional[str]:
        """
        Translate text to target language
        
        Args:
            text: Text to translate
            source_lang: Source language code (auto-detect if None)
            dest_lang: Destination language (uses self.target_language if None)
            
        Returns:
            Translated text or None if translation fails
        """
        if not self.enable_translation:
            return None
        
        if not text or len(text.strip()) < 5:
            return None
        
        dest_lang = dest_lang or self.target_language
        
        # Don't translate if already in target language
        if source_lang and source_lang == dest_lang:
            return None
        
        try:
            if self.translation_backend == TranslationBackend.GOOGLETRANS and self.google_translator:
                return await self._translate_googletrans(text, source_lang, dest_lang)
            
            elif self.translation_backend == TranslationBackend.DEEP_TRANSLATOR and DEEP_TRANSLATOR_AVAILABLE:
                return await self._translate_deep(text, source_lang, dest_lang)
            
            else:
                self.logger.warning(f"No translation backend available: {self.translation_backend}")
                return None
                
        except Exception as e:
            self.logger.error(f"Translation failed: {e}")
            return None
    
    async def _translate_googletrans(self, text: str, source: Optional[str], dest: str) -> Optional[str]:
        """Translate using googletrans library"""
        try:
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, 
                lambda: self.google_translator.translate(
                    text, 
                    src=source or 'auto',
                    dest=dest
                )
            )
            return result.text
        except Exception as e:
            self.logger.error(f"googletrans translation error: {e}")
            return None
    
    async def _translate_deep(self, text: str, source: Optional[str], dest: str) -> Optional[str]:
        """Translate using deep-translator library"""
        try:
            # Deep translator doesn't support async, run in executor
            loop = asyncio.get_event_loop()
            
            # Create translator instance
            translator = DeepGoogleTranslator(
                source=source or 'auto',
                target=dest
            )
            
            result = await loop.run_in_executor(
                None,
                lambda: translator.translate(text)
            )
            return result
        except Exception as e:
            self.logger.error(f"deep-translator error: {e}")
            return None
    
    async def process_article(self, 
                            title: str, 
                            description: Optional[str] = None,
                            content: Optional[str] = None,
                            translate_content: bool = False) -> Dict[str, any]:
        """
        Process article: detect language and optionally translate
        
        Args:
            title: Article title
            description: Article description
            content: Full article content
            translate_content: Whether to translate full content (can be slow for long articles)
            
        Returns:
            Dict with:
                - detected_language: Language code
                - confidence: Detection confidence
                - translated_title: Translated title (if enabled)
                - translated_description: Translated description (if enabled)
                - translated_content: Translated content (if enabled and translate_content=True)
                - should_translate: Whether translation is recommended
        """
        # Combine text for better detection (prioritize title and content)
        detection_text = title
        if content:
            detection_text = f"{title}. {content[:500]}"
        elif description:
            detection_text = f"{title}. {description}"
        
        # Detect language
        lang_result = self.detect_language(detection_text)
        
        result = {
            'detected_language': lang_result['language'] if lang_result else 'unknown',
            'confidence': lang_result['confidence'] if lang_result else 0.0,
            'probabilities': lang_result.get('probabilities', []) if lang_result else [],
            'translated_title': None,
            'translated_description': None,
            'translated_content': None,
            'should_translate': False
        }
        
        # Determine if translation is needed
        if lang_result and lang_result['language'] != self.target_language:
            result['should_translate'] = True
            
            if self.enable_translation:
                source_lang = lang_result['language']
                
                # Translate title
                if title:
                    result['translated_title'] = await self.translate_text(
                        title, source_lang, self.target_language
                    )
                
                # Translate description
                if description:
                    result['translated_description'] = await self.translate_text(
                        description, source_lang, self.target_language
                    )
                
                # Translate content (optional, can be slow for long articles)
                if translate_content and content and len(content) > 0:
                    # For long content, might want to chunk or limit
                    # Google Translate has a limit of ~5000 characters per request
                    if len(content) > 4500:
                        self.logger.warning(f"Content is long ({len(content)} chars), translating first 4500 chars")
                        content_to_translate = content[:4500]
                    else:
                        content_to_translate = content
                    
                    result['translated_content'] = await self.translate_text(
                        content_to_translate, source_lang, self.target_language
                    )
        
        return result


# Convenience functions for quick usage
async def detect_article_language(title: str, content: Optional[str] = None) -> Tuple[str, float]:
    """
    Quick language detection for an article
    
    Returns:
        (language_code, confidence)
    """
    service = LanguageService(enable_translation=False)
    text = f"{title}. {content[:500] if content else ''}"
    result = service.detect_language(text)
    return (result['language'], result['confidence']) if result else ('unknown', 0.0)


async def translate_article(title: str, 
                           description: Optional[str] = None,
                           source_lang: Optional[str] = None,
                           target_lang: str = 'pt') -> Dict[str, Optional[str]]:
    """
    Quick translation of article text
    
    Returns:
        Dict with 'title' and 'description' translations
    """
    service = LanguageService(target_language=target_lang, enable_translation=True)
    
    return {
        'title': await service.translate_text(title, source_lang, target_lang),
        'description': await service.translate_text(description, source_lang, target_lang) if description else None
    }


# Testing
async def main():
    """Test language detection and translation"""
    service = LanguageService(
        translation_backend=TranslationBackend.GOOGLETRANS,
        target_language='pt',
        enable_translation=True
    )
    
    # Test articles in different languages
    test_articles = [
        {
            'title': 'Breaking: NASA discovers water on Mars',
            'description': 'Scientists confirm presence of liquid water beneath the Martian surface',
            'lang': 'en'
        },
        {
            'title': 'Brasil vence Copa do Mundo pela sexta vez',
            'description': 'Seleção brasileira conquista o hexacampeonato mundial',
            'lang': 'pt'
        },
        {
            'title': 'La inteligencia artificial revoluciona la medicina',
            'description': 'Nuevos algoritmos detectan enfermedades con precisión del 99%',
            'lang': 'es'
        }
    ]
    
    print("=" * 70)
    print("LANGUAGE DETECTION & TRANSLATION TEST")
    print("=" * 70)
    
    for article in test_articles:
        print(f"\n📰 Original ({article['lang']}):")
        print(f"   Title: {article['title']}")
        print(f"   Description: {article['description']}")
        
        result = await service.process_article(
            title=article['title'],
            description=article['description']
        )
        
        print(f"\n🔍 Detection:")
        print(f"   Language: {result['detected_language']} ({result['confidence']:.2%} confidence)")
        print(f"   Should translate: {result['should_translate']}")
        
        if result['translated_title']:
            print(f"\n🌐 Translation (pt):")
            print(f"   Title: {result['translated_title']}")
            if result['translated_description']:
                print(f"   Description: {result['translated_description']}")
        
        print("-" * 70)


if __name__ == '__main__':
    asyncio.run(main())
