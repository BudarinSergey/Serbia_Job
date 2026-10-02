"""Offline M2M100 int8. Only fixed local model assets, no remote Python code."""
from functools import lru_cache
from pathlib import Path
import re

MODEL_PATH=Path(__file__).resolve().parents[1]/'models'/'m2m100-int8'
VERSION='m2m100-int8-7c1b262-v1'
CYR='абвгдђежзијклљмнњопрстћуфхцчџш'
LAT=['a','b','v','g','d','đ','e','ž','z','i','j','k','l','lj','m','n','nj','o','p','r','s','t','ć','u','f','h','c','č','dž','š']
TABLE={ord(a):b for a,b in zip(CYR,LAT)}
TABLE.update({ord(a.upper()):b.capitalize() for a,b in zip(CYR,LAT)})


@lru_cache(maxsize=1)
def runtime():
    import ctranslate2
    import sentencepiece
    from langid.langid import LanguageIdentifier,model
    detector=LanguageIdentifier.from_modelstring(model,norm_probs=True)
    # Latin-script Serbian is often classified as Croatian/Bosnian.
    detector.set_languages(['en','sr','ru','hr','bs'])
    sp=sentencepiece.SentencePieceProcessor(model_file=str(MODEL_PATH/'sentencepiece.bpe.model'))
    translator=ctranslate2.Translator(str(MODEL_PATH),device='cpu',compute_type='int8',inter_threads=1,intra_threads=2)
    return translator,sp,detector


def local_translate(text):
    from telegram_bot.automatic_translation import TranslationUnavailable,validate
    try:
        model,sp,detector=runtime()
        source,confidence=detector.classify(text)
        source={'hr':'sr','bs':'sr'}.get(source,source)
        if confidence<0.65:
            raise TranslationUnavailable('Source language uncertain')
        tokens=sp.encode(text,out_type=str)
        if len(tokens)>256:
            raise TranslationUnavailable('Phrase too long; do not truncate')
        pair={}
        for target in ('sr','ru'):
            if target==source:
                output=text
            else:
                result=model.translate_batch([[f'__{source}__']+tokens+['</s>']],
                    target_prefix=[[f'__{target}__']],beam_size=4,max_decoding_length=300)[0]
                pieces=result.hypotheses[0]
                if len(pieces)>=300:
                    raise TranslationUnavailable('Translation truncated')
                output=sp.decode([p for p in pieces if not p.startswith('__') and p not in ('</s>','<s>')])
            pair[target]=output.translate(TABLE) if target=='sr' else output
        return validate(text,pair)
    except (ImportError,RuntimeError,OSError,ValueError) as exc:
        raise TranslationUnavailable('Local translation unavailable or requires review') from None
