// Hand-written transcript; no repository files or real conversations are read.
export function transcript() {
  const use = (id, path) => ({ tool_use_id: id, tool: 'Read', input: { file_path: path } });
  const message = (role, text = '', toolUses = [], toolResults = []) =>
    ({ role, text, toolUses, toolResults });
  return [
    message('user', '파서의 국소 버그를 수정하세요. 운영 데이터를 변경하지 말고 계약 변경은 make check로 검증하세요.'),
    message('assistant', '', [use('obsolete', 'downloader/old-debug.txt')]),
    message('user', '', [], [{ tool_use_id: 'obsolete', text: 'obsolete download log\n'.repeat(700) }]),
    message('assistant', '이 다운로드 로그는 해결을 마친 이전 조사 결과로 현재 파서 작업에는 필요 없습니다.'),
    message('assistant', '', [use('rerunnable', 'parser_tidy/monsters.py')]),
    message('user', '', [], [{ tool_use_id: 'rerunnable', text: 'old source; can re-read\n'.repeat(400) }]),
    message('assistant', '', [use('contract', 'docs/data-contracts.md')]),
    message('user', '', [], [{ tool_use_id: 'contract', text: 'Contract: normalized IDs and numeric units must remain unchanged.' }]),
    message('assistant', '공통 계약 검증과 미완료 작업을 보존해야 합니다.'),
    message('user', '현재 목표는 파서의 문자열 처리 수정입니다. 이전 다운로드 조사는 끝났습니다.'),
    message('assistant', '영향 범위와 검증 경로를 확인했습니다.'),
    message('user', '이어서 현재 파서 작업을 진행하세요.'),
    message('assistant', '최근 작업은 유지하세요.'),
    message('assistant', '', [use('recent', 'parser_tidy/current.py')]),
    message('user', '', [], [{ tool_use_id: 'recent', text: 'recent output\n'.repeat(400) }]),
    message('assistant', '아직 구현을 끝내지 않았습니다.'),
    message('user', '사용자 지시와 최근 결과를 보존하세요.'),
    message('assistant', '수정 후 관련 검증을 실행하겠습니다.'),
  ];
}

export function fakeResponse(body) {
  const answers = Object.fromEntries(Object.keys(body.questions).map(name => {
    const keep = name.endsWith('_t3') || name === 'call_t2';
    return [name, { type: 'noul', noul: keep ? 0.95 : 0.05 }];
  }));
  return { status: 200, ok: true, text: JSON.stringify({ model: body.model, answers,
    usage: { input_tokens: 1000, output_tokens: 100 } }) };
}

export function textIsPreserved(before, after) {
  const texts = messages => messages.filter(message => message.text.length > 0).map(message => message.text);
  return JSON.stringify(texts(before)) === JSON.stringify(texts(after));
}
