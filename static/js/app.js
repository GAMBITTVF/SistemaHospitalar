// Máscaras de campos, busca de CEP (ViaCEP) e confirmações.
(function () {
  function digitos(v) { return (v || '').replace(/\D/g, ''); }

  var mascaras = {
    cpf: function (v) {
      v = digitos(v).slice(0, 11);
      return v.replace(/(\d{3})(\d)/, '$1.$2').replace(/(\d{3})(\d)/, '$1.$2').replace(/(\d{3})(\d{1,2})$/, '$1-$2');
    },
    cns: function (v) {
      v = digitos(v).slice(0, 15);
      return v.replace(/(\d{3})(\d)/, '$1 $2').replace(/(\d{3} \d{4})(\d)/, '$1 $2').replace(/(\d{3} \d{4} \d{4})(\d)/, '$1 $2');
    },
    cep: function (v) {
      v = digitos(v).slice(0, 8);
      return v.replace(/(\d{5})(\d)/, '$1-$2');
    },
    telefone: function (v) {
      v = digitos(v).slice(0, 11);
      if (v.length > 10) return v.replace(/(\d{2})(\d{5})(\d{0,4})/, '($1) $2-$3');
      return v.replace(/(\d{2})(\d{0,4})(\d{0,4})/, function (_, a, b, c) {
        return '(' + a + ') ' + b + (c ? '-' + c : '');
      });
    }
  };

  document.querySelectorAll('[data-mascara]').forEach(function (campo) {
    var fn = mascaras[campo.dataset.mascara];
    if (!fn) return;
    campo.value = fn(campo.value);
    campo.addEventListener('input', function () { campo.value = fn(campo.value); });
  });

  // Preenchimento automático do endereço pelo CEP (serviço público ViaCEP).
  var cep = document.querySelector('[data-mascara="cep"]');
  if (cep) {
    cep.addEventListener('blur', function () {
      var c = digitos(cep.value);
      if (c.length !== 8) return;
      fetch('https://viacep.com.br/ws/' + c + '/json/')
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.erro) return;
          var mapa = { logradouro: d.logradouro, bairro: d.bairro, cidade: d.localidade, uf: d.uf };
          Object.keys(mapa).forEach(function (nome) {
            var el = document.querySelector('[name="' + nome + '"]');
            if (el && !el.value && mapa[nome]) el.value = nome === 'cidade' ? mapa[nome].toUpperCase() : mapa[nome];
          });
          var numero = document.querySelector('[name="numero"]');
          if (numero) numero.focus();
        })
        .catch(function () { /* sem internet: preenchimento manual */ });
    });
  }

  document.querySelectorAll('form[data-confirmar]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (!window.confirm(form.dataset.confirmar)) e.preventDefault();
    });
  });

  // Mostra o campo de senha somente quando o médico marca "assinar".
  document.querySelectorAll('[data-alterna]').forEach(function (chk) {
    var alvo = document.getElementById(chk.dataset.alterna);
    function atualizar() { if (alvo) alvo.style.display = chk.checked ? '' : 'none'; }
    chk.addEventListener('change', atualizar);
    atualizar();
  });
})();
