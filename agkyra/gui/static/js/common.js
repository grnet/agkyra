function toggleFooterClass(){
    var mainH = parseInt($('.js-main').outerHeight());
    var windowH = parseInt($(window).height());
    var res = windowH - mainH;
    var footerHeight = $('.js-footer').outerHeight();
    if (res>0) {
        $('.js-footer').addClass('normal');
        $('.js-main').css('padding-bottom', footerHeight);
    } else {
        $('.js-footer').removeClass('normal');
        $('.js-main').removeAttr('style');
    }
}


$(document).ready( function() {
    toggleFooterClass();
})

$(window).resize(function() {

    toggleFooterClass();
});
