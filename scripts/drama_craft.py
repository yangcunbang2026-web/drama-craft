#!/usr/bin/env python3
"""Offline utilities for Drama Craft. SPDX-License-Identifier: MIT."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (
    '.gitattributes', '.gitignore', '.github/workflows/ci.yml', 'LICENSE', 'LICENSE.code',
    'README.md', 'SKILL.md', 'agents/openai.yaml', 'references/ATTRIBUTION.md',
    'references/workflow.md', 'scripts/drama_craft.py', 'tests/test_cli.py',
)
BUNDLE_FILES = (
    'SKILL.md', 'agents/openai.yaml', 'references/workflow.md',
    'references/ATTRIBUTION.md', 'LICENSE', 'LICENSE.code',
)
IGNORED_DIRS = {'.git', '__pycache__', '.venv', 'dist', 'projects'}


class ValidationError(ValueError):
    pass


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8-sig')


def prompt_catalog(root: Path = ROOT) -> dict[str, tuple[str, str]]:
    text = read(root / 'references/workflow.md')
    entries = re.findall(
        r'^\*\*(T\d{2}) ([^\n]+)\*\*\n\n```text\n(.*?)\n```',
        text, flags=re.MULTILINE | re.DOTALL,
    )
    result: dict[str, tuple[str, str]] = {}
    for key, title, body in entries:
        if key in result:
            raise ValidationError(f'Duplicate prompt: {key}')
        result[key] = (title, body)
    return result


def anchor(title: str) -> str:
    title = re.sub(r'[^\w\-\s]', '', title.lower(), flags=re.UNICODE)
    return re.sub(r'\s+', '-', title.strip())


def validate(root: Path = ROOT) -> dict[str, int]:
    root = root.resolve()
    errors: list[str] = []
    expected = set(PUBLIC_FILES)
    for name in PUBLIC_FILES:
        path = root / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
            errors.append(f'Missing file or unsupported symlink: {name}')
    for path in root.rglob('*'):
        rel = path.relative_to(root)
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        if path.is_file() and rel.as_posix() not in expected:
            errors.append(f'Unexpected distribution file: {rel.as_posix()}')
    if errors:
        raise ValidationError('\n'.join(errors))

    patterns = (
        (r'(?<![A-Za-z0-9_])[A-Za-z]:[\\/]', 'absolute Windows path'),
        (r'/(?:Users|home|mnt|tmp)/[^\s)]+', 'absolute personal path'),
        (r'gh[pousr]_[A-Za-z0-9]{20,}', 'possible GitHub token'),
        (r'github_pat_[A-Za-z0-9_]{20,}', 'possible GitHub token'),
        (r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', 'private key'),
    )
    link_count = 0
    for name in PUBLIC_FILES:
        text = read(root / name)
        for pattern, label in patterns:
            if re.search(pattern, text):
                errors.append(f'{name}: {label}')
        if name.endswith('.md'):
            if len(re.findall(r'^```', text, flags=re.MULTILINE)) % 2:
                errors.append(f'{name}: unclosed fenced block')
            for target in re.findall(r'\]\(([^)\n]+)\)', text):
                if '://' in target or target.startswith('mailto:'):
                    continue
                rel, _, heading = target.strip('<>').partition('#')
                dest = ((root / name).parent / rel).resolve() if rel else root / name
                if not dest.is_relative_to(root) or not dest.is_file():
                    errors.append(f'{name}: broken or external local link: {target}')
                    continue
                if heading:
                    headings = re.findall(r'^#{1,6} (.+)$', read(dest), flags=re.MULTILINE)
                    if heading not in headings and heading not in {anchor(h) for h in headings}:
                        errors.append(f'{name}: missing heading: {target}')
                link_count += 1
            width = None
            for line in text.splitlines():
                if not line.startswith('|'):
                    width = None
                    continue
                columns = len(re.split(r'(?<!\\)\|', line))
                if width is None:
                    width = columns
                elif width != columns:
                    errors.append(f'{name}: inconsistent table columns')

    entry = read(root / 'SKILL.md')
    if not entry.startswith('---\nname: drama-craft\ndescription: "'):
        errors.append('SKILL.md: unsupported frontmatter or skill name')
    try:
        front = entry.split('---', 2)[1]
        description = next(line.split(':', 1)[1].strip()
                           for line in front.splitlines() if line.startswith('description:'))
        if not isinstance(json.loads(description), str):
            raise ValueError('description must be a string')
    except (IndexError, StopIteration, ValueError):
        errors.append('SKILL.md: description must be a quoted string')
    catalog = prompt_catalog(root)
    if list(catalog) != [f'T{i:02}' for i in range(27)]:
        errors.append('workflow: expected exactly T00 through T26, in order')
    if any(not body.strip() for _, body in catalog.values()):
        errors.append('workflow: empty prompt')
    for name in ('LICENSE', 'LICENSE.code'):
        if len(read(root / name)) < 500:
            errors.append(f'{name}: license text missing')
    attribution = read(root / 'references/ATTRIBUTION.md')
    if 'Serge Shima' not in attribution or 'CC BY 4.0' not in attribution:
        errors.append('Missing upstream attribution')
    if errors:
        raise ValidationError('\n'.join(errors))
    return {'files': len(PUBLIC_FILES), 'prompts': len(catalog), 'local_links': link_count}


def new_directory(destination: Path) -> Path:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f'Destination exists; nothing overwritten: {destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    return destination


def install(destination: Path, root: Path = ROOT) -> None:
    validate(root)
    destination = new_directory(destination)
    for name in BUNDLE_FILES:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)


def initialize(destination: Path, idea: str) -> None:
    destination = new_directory(destination)
    content = '''# 制作主单

状态：工作稿；尚未生成媒体或完成声画验收。

## 制作约定

故事想法：{idea}

作品用途、不可改设定、画幅、语言、规模、视觉方向、声音路线、现有资产、
工具、授权范围与本轮交付：按已有材料补充，未知项明确标记。

## 剧本主源

主稿路径、版本、场号与准确台词：待创建或引用已有稿。

## 资产

角色、地点、道具的ID、状态版、真实文件、参考职责和已核范围：待补。

## 逐镜卡

镜号、观众信息、人物目的、触发、首态、关键变化、终态、机位、轴线、
摄影路径、准确声音、源段边界、提示词、相邻承接及失败条件：按本批填写。

## 实际任务与采用

暂无任务。发生实际操作后记录输入版本、任务、原片原声、费用、
检查证据、可用区间、工程和交付版本。

## 当前缺口与下一步

先依据输入完成故事或诊断，未知事实与创作提案分开。
'''.format(idea=idea or '待提供')
    with (destination / 'PROJECT.md').open('x', encoding='utf-8') as handle:
        handle.write(content)


def pack(output: Path, root: Path = ROOT) -> None:
    validate(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name in sorted(BUNDLE_FILES):
            info = zipfile.ZipInfo('drama-craft/' + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, (root / name).read_bytes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('validate', help='Check the public distribution')
    sub.add_parser('prompts', help='List prompts from the single workflow source')
    prompt = sub.add_parser('prompt', help='Print a template and optional local context')
    prompt.add_argument('id')
    prompt.add_argument('--context', type=Path)
    init = sub.add_parser('init', help='Create a new production record directory')
    init.add_argument('destination', type=Path)
    init.add_argument('--idea', default='')
    inst = sub.add_parser('install', help='Copy the portable skill; never overwrite a directory')
    inst.add_argument('--destination', required=True, type=Path)
    package = sub.add_parser('pack', help='Create a deterministic skill ZIP without project data')
    package.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'validate':
            print(json.dumps(validate(), ensure_ascii=False))
        elif args.command in {'prompt', 'prompts'}:
            catalog = prompt_catalog()
            if args.command == 'prompts':
                for key, (title, _) in catalog.items():
                    print(f'{key} {title}')
            else:
                key = args.id.upper()
                if key not in catalog:
                    raise ValidationError(f'Unknown prompt: {key}')
                title, body = catalog[key]
                print(f'{key} {title}\n\n{body}')
                if args.context:
                    print('\n项目上下文（由助手据此填写模板字段）：\n' + read(args.context))
        elif args.command == 'init':
            initialize(args.destination, args.idea)
            print(f'Created {args.destination / "PROJECT.md"}')
        elif args.command == 'install':
            install(args.destination)
            print(f'Installed {args.destination}')
        elif args.command == 'pack':
            pack(args.output)
            print(f'Packed {args.output}')
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
